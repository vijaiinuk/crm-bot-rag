"""JWT validation and the request-scoped CurrentUser dependency.

Same code path locally and in production: tokens are verified against a JWKS
fetched over HTTP. Identity comes only from verified claims; allowed modules
come only from the EntitlementProvider (CLAUDE.md rule 1).
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from chatbot.config import Settings
from chatbot.ports.entitlements import EntitlementError, EntitlementProvider, Principal

log = logging.getLogger(__name__)

ALGORITHM = "RS256"
REQUIRED_CLAIMS = ["iss", "aud", "sub", "iat", "exp"]


class AuthError(Exception):
    """The token is not acceptable. Maps to 401."""


class AuthUnavailable(Exception):
    """Keys could not be obtained, so no token can be verified. Maps to 503."""


class JwksSource(Protocol):
    async def get_key(self, kid: str) -> jwt.PyJWK: ...


class HttpJwksSource:
    """Fetches and caches a JWKS. An unknown `kid` triggers one rate-limited refetch
    (to pick up key rotation) before the token is rejected."""

    def __init__(
        self,
        url: str,
        *,
        ttl_s: float,
        client: httpx.AsyncClient | None = None,
        min_refresh_interval_s: float = 30.0,
    ) -> None:
        self._url = url
        self._ttl_s = ttl_s
        self._min_refresh_s = min_refresh_interval_s
        self._client = client or httpx.AsyncClient(timeout=5.0)
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._lock = asyncio.Lock()

    async def get_key(self, kid: str) -> jwt.PyJWK:
        keys = await self._load(force=False)
        if kid not in keys and self._may_force_refresh():
            keys = await self._load(force=True)
        try:
            return keys[kid]
        except KeyError:
            raise AuthError("unknown signing key") from None

    async def aclose(self) -> None:
        await self._client.aclose()

    def _may_force_refresh(self) -> bool:
        return (
            self._fetched_at is None or time.monotonic() - self._fetched_at >= self._min_refresh_s
        )

    def _fresh(self) -> bool:
        return self._fetched_at is not None and time.monotonic() - self._fetched_at < self._ttl_s

    async def _load(self, *, force: bool) -> dict[str, jwt.PyJWK]:
        async with self._lock:
            if self._fresh() and not force:
                return self._keys
            try:
                resp = await self._client.get(self._url)
                resp.raise_for_status()
                jwk_set = jwt.PyJWKSet.from_dict(resp.json())
            except (httpx.HTTPError, ValueError, jwt.PyJWKSetError) as e:
                # Fail closed: no stale keys, no skipping verification.
                raise AuthUnavailable(f"JWKS fetch failed: {type(e).__name__}") from e
            self._keys = {k.key_id: k for k in jwk_set.keys if k.key_id}
            self._fetched_at = time.monotonic()
            return self._keys


async def decode_verified_claims(
    token: str, jwks: JwksSource, settings: Settings
) -> dict[str, Any]:
    """Verify signature, algorithm, issuer, audience and expiry; return the claims."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as e:
        raise AuthError("malformed token") from e
    # Pin the algorithm before touching keys: blocks `none` and HS256 key confusion.
    if header.get("alg") != ALGORITHM:
        raise AuthError("unexpected algorithm")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise AuthError("missing kid")

    key = await jwks.get_key(kid)
    try:
        claims = jwt.decode(
            token,
            key.key,
            algorithms=[ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            leeway=settings.jwt_leeway_s,
            options={"require": REQUIRED_CLAIMS},
        )
    except jwt.InvalidTokenError as e:
        raise AuthError(type(e).__name__) from e
    return claims


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    values = {name: claims.get(name) for name in ("sub", "tenant", "role")}
    for name, value in values.items():
        if not isinstance(value, str) or not value:
            raise AuthError(f"claim {name!r} missing or not a string")
    return Principal(sub=values["sub"], tenant=values["tenant"], role=values["role"])  # type: ignore[arg-type]


async def verify_token(token: str, jwks: JwksSource, settings: Settings) -> Principal:
    return principal_from_claims(await decode_verified_claims(token, jwks, settings))


@dataclass(frozen=True, slots=True)
class AuthContext:
    settings: Settings
    jwks: JwksSource
    entitlements: EntitlementProvider


@dataclass(frozen=True, slots=True)
class CurrentUser:
    principal: Principal
    allowed_modules: frozenset[str]


_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, "invalid or missing token", {"WWW-Authenticate": "Bearer"}
    )


Bearer = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


@dataclass(frozen=True, slots=True)
class Claims:
    principal: Principal
    raw: dict[str, Any]


async def authenticate(request: Request, creds: HTTPAuthorizationCredentials | None) -> Claims:
    """Verified claims, or 401 (bad/missing token) / 503 (keys unavailable)."""
    ctx: AuthContext = request.app.state.auth
    if creds is None:
        raise _unauthorized()
    try:
        claims = await decode_verified_claims(creds.credentials, ctx.jwks, ctx.settings)
        principal = principal_from_claims(claims)
    except AuthError as e:
        log.info("auth rejected: %s", e)
        raise _unauthorized() from None
    except AuthUnavailable as e:
        log.error("auth unavailable: %s", e)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "auth unavailable") from None
    return Claims(principal=principal, raw=claims)


async def current_user(request: Request, creds: Bearer) -> CurrentUser:
    ctx: AuthContext = request.app.state.auth
    principal = (await authenticate(request, creds)).principal

    try:
        allowed = await ctx.entitlements.resolve(principal)
    except EntitlementError as e:
        log.warning("entitlements denied for %s@%s: %s", principal.role, principal.tenant, e)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not entitled") from None
    return CurrentUser(principal=principal, allowed_modules=allowed)


CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]
