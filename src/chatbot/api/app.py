from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from chatbot.adapters import local_jwt
from chatbot.adapters.local_catalogue import check_covers, load_catalogue
from chatbot.adapters.local_entitlements import LocalEntitlementProvider
from chatbot.adapters.mock_responder import MockResponder
from chatbot.api import chat
from chatbot.api.auth import AuthContext, CurrentUserDep, HttpJwksSource, JwksSource
from chatbot.api.dev import build_dev_router
from chatbot.config import Settings
from chatbot.ports.catalogue import ModuleCatalogue
from chatbot.ports.entitlements import EntitlementProvider
from chatbot.ports.responder import Responder
from chatbot.tracing.log import configure_logging


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
    catalogue: ModuleCatalogue | None = None,
    responder: Responder | None = None,
) -> FastAPI:
    settings = settings or Settings()
    configure_logging()

    if entitlements is None:
        if settings.env == "prod":
            raise RuntimeError("no production entitlement provider configured")
        entitlements = LocalEntitlementProvider.from_file(settings.personas_path)

    if catalogue is None:
        catalogue = load_catalogue(settings.catalogue_path)
    if isinstance(entitlements, LocalEntitlementProvider):
        check_covers(catalogue, entitlements.modules)

    if responder is None:
        if settings.env == "prod":
            raise RuntimeError("no production responder configured")
        responder = MockResponder(catalogue, token_delay_s=settings.mock_token_delay_s)

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
    app.state.responder = responder
    app.include_router(chat.router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/me")
    async def me(user: CurrentUserDep) -> MeResponse:
        p = user.principal
        return MeResponse(
            sub=p.sub, tenant=p.tenant, role=p.role, allowed_modules=sorted(user.allowed_modules)
        )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,  # bearer tokens, not cookies
        )

    if settings.env == "local":
        _mount_local_routes(app, settings, entitlements)

    return app


def _mount_local_routes(
    app: FastAPI, settings: Settings, entitlements: EntitlementProvider
) -> None:
    """Local stand-ins for the CRM identity provider: its JWKS endpoint and the
    harness's token minting. Never mounted outside local."""
    try:
        key = local_jwt.load_private_key(settings.keys_dir)
    except FileNotFoundError:
        raise RuntimeError(f"no signing key in {settings.keys_dir}; run `make keys`") from None
    body = local_jwt.jwks(key.public_key())

    @app.get("/.well-known/jwks.json", include_in_schema=False)
    async def jwks() -> dict[str, Any]:
        return body

    if not isinstance(entitlements, LocalEntitlementProvider):
        raise RuntimeError("dev token routes need the local persona file")
    app.include_router(build_dev_router(settings, key, entitlements))
