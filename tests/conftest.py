from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from chatbot.adapters import local_jwt
from chatbot.adapters.local_entitlements import LocalEntitlementProvider
from chatbot.api.app import create_app
from chatbot.api.auth import HttpJwksSource
from chatbot.config import Settings

ISSUER = "http://issuer.test"
AUDIENCE = "crm-help-bot"
JWKS_URL = "http://issuer.test/.well-known/jwks.json"

PERSONAS = {
    "sales_manager@acme": frozenset({"core", "contacts", "deals", "campaigns"}),
    "sales_rep@globex": frozenset({"core", "contacts", "deals"}),
}


@pytest.fixture(scope="session")
def signing_key() -> rsa.RSAPrivateKey:
    return local_jwt.generate_private_key()


@pytest.fixture(scope="session")
def other_key() -> rsa.RSAPrivateKey:
    return local_jwt.generate_private_key()


@pytest.fixture
def settings() -> Settings:
    return Settings(env="test", jwt_issuer=ISSUER, jwt_audience=AUDIENCE, jwks_url=JWKS_URL)


@pytest.fixture
def jwks_state(signing_key: rsa.RSAPrivateKey) -> dict[str, Any]:
    """Mutable so tests can make the JWKS endpoint fail or count fetches."""
    return {"fail": False, "fetches": 0, "body": local_jwt.jwks(signing_key.public_key())}


@pytest.fixture
def jwks_source(settings: Settings, jwks_state: dict[str, Any]) -> HttpJwksSource:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == JWKS_URL
        jwks_state["fetches"] += 1
        if jwks_state["fail"]:
            return httpx.Response(503)
        return httpx.Response(200, json=jwks_state["body"])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HttpJwksSource(settings.jwks_url, ttl_s=settings.jwks_cache_ttl_s, client=client)


@pytest.fixture
async def client(
    settings: Settings, jwks_source: HttpJwksSource
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        settings,
        jwks_source=jwks_source,
        entitlements=LocalEntitlementProvider(PERSONAS),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as c:
        yield c


MintToken = Callable[..., str]


@pytest.fixture
def mint(signing_key: rsa.RSAPrivateKey) -> MintToken:
    def _mint(**overrides: Any) -> str:
        args: dict[str, Any] = {
            "sub": "u-1",
            "tenant": "acme",
            "role": "sales_manager",
            "issuer": ISSUER,
            "audience": AUDIENCE,
        } | overrides
        key = args.pop("key", signing_key)
        return local_jwt.mint_token(key, **args)

    return _mint
