"""Local-only helpers for the dev harness and admin app: list personas and
admins, mint their tokens.

Mounted only when env == "local" (see create_app). Minting is the local IdP's
job; the tokens still go through the full validation path on every request.
"""

from pathlib import Path

import yaml
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from chatbot.adapters import local_jwt
from chatbot.adapters.local_entitlements import LocalEntitlementProvider
from chatbot.config import Settings

DEV_TOKEN_TTL_S = 3600


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona: str


class AdminTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    admin: str


class TokenResponse(BaseModel):
    token: str
    expires_in: int


def load_admins(path: Path) -> dict[str, str]:
    """admin id (`name@ops`) -> admin_role, for local minting only."""
    raw = yaml.safe_load(path.read_text())
    admins = raw.get("admins") if isinstance(raw, dict) else None
    if not isinstance(admins, dict) or not all(
        isinstance(k, str) and v in ("viewer", "editor", "publisher") for k, v in admins.items()
    ):
        raise ValueError(f"{path}: admins must map name@ops to viewer|editor|publisher")
    return dict(admins)


def build_dev_router(
    settings: Settings,
    key: rsa.RSAPrivateKey,
    personas: LocalEntitlementProvider,
    admins: dict[str, str],
) -> APIRouter:
    router = APIRouter(prefix="/dev", include_in_schema=False)

    @router.get("/personas")
    async def list_personas() -> list[str]:
        return sorted(personas.persona_ids)

    @router.post("/token")
    async def mint(body: TokenRequest) -> TokenResponse:
        if body.persona not in personas.persona_ids:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown persona")
        role, _, tenant = body.persona.partition("@")
        token = local_jwt.mint_token(
            key,
            sub=f"user-{role}-{tenant}",
            tenant=tenant,
            role=role,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            ttl_s=DEV_TOKEN_TTL_S,
        )
        return TokenResponse(token=token, expires_in=DEV_TOKEN_TTL_S)

    @router.get("/admins")
    async def list_admins() -> dict[str, str]:
        return admins

    @router.post("/admin-token")
    async def mint_admin(body: AdminTokenRequest) -> TokenResponse:
        role = admins.get(body.admin)
        if role is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown admin")
        token = local_jwt.mint_token(
            key,
            sub=f"admin-{body.admin.partition('@')[0]}",
            tenant=settings.admin_tenant,
            role="ops_admin",
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            ttl_s=DEV_TOKEN_TTL_S,
            extra_claims={"admin_role": role},
        )
        return TokenResponse(token=token, expires_in=DEV_TOKEN_TTL_S)

    return router
