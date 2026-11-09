from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from chatbot.adapters import local_jwt
from chatbot.adapters.local_entitlements import LocalEntitlementProvider
from chatbot.api.auth import AuthContext, CurrentUserDep, HttpJwksSource, JwksSource
from chatbot.config import Settings
from chatbot.ports.entitlements import EntitlementProvider


class MeResponse(BaseModel):
    sub: str
    tenant: str
    role: str
    allowed_modules: list[str]


def create_app(
    settings: Settings | None = None,
    *,
    jwks_source: JwksSource | None = None,
    entitlements: EntitlementProvider | None = None,
) -> FastAPI:
    settings = settings or Settings()

    if entitlements is None:
        if settings.env == "prod":
            raise RuntimeError("no production entitlement provider configured")
        entitlements = LocalEntitlementProvider.from_file(settings.personas_path)

    owned_jwks: HttpJwksSource | None = None
    if jwks_source is None:
        owned_jwks = HttpJwksSource(settings.jwks_url, ttl_s=settings.jwks_cache_ttl_s)
        jwks_source = owned_jwks

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if owned_jwks is not None:
            await owned_jwks.aclose()

    app = FastAPI(title="CRM help bot", lifespan=lifespan)
    app.state.auth = AuthContext(settings=settings, jwks=jwks_source, entitlements=entitlements)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/me")
    async def me(user: CurrentUserDep) -> MeResponse:
        p = user.principal
        return MeResponse(
            sub=p.sub, tenant=p.tenant, role=p.role, allowed_modules=sorted(user.allowed_modules)
        )

    if settings.env == "local":
        _mount_local_jwks(app, settings)

    return app


def _mount_local_jwks(app: FastAPI, settings: Settings) -> None:
    """Local stand-in for the CRM issuer's JWKS endpoint. Never mounted outside local."""
    try:
        public_key = local_jwt.load_private_key(settings.keys_dir).public_key()
    except FileNotFoundError:
        raise RuntimeError(f"no signing key in {settings.keys_dir}; run `make keys`") from None
    body = local_jwt.jwks(public_key)

    @app.get("/.well-known/jwks.json", include_in_schema=False)
    async def jwks() -> dict[str, Any]:
        return body
