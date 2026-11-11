"""Local-only helpers for the dev harness: list personas, mint persona tokens.

Mounted only when env == "local" (see create_app). Minting is the local IdP's
job; the tokens still go through the full validation path on every request.
"""

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


class TokenResponse(BaseModel):
    token: str
    expires_in: int


def build_dev_router(
    settings: Settings, key: rsa.RSAPrivateKey, personas: LocalEntitlementProvider
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

    return router
