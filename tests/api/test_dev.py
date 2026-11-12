from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from chatbot.adapters import local_jwt
from chatbot.adapters.local_catalogue import load_catalogue
from chatbot.adapters.local_entitlements import LocalEntitlementProvider
from chatbot.adapters.mock_admin import build_mock_admin_service
from chatbot.adapters.mock_responder import MockResponder
from chatbot.api.app import create_app
from chatbot.api.auth import AuthError
from chatbot.config import Settings
from tests.conftest import PERSONAS

ORIGIN = "http://localhost:5173"


class StaticJwks:
    """Serves the local key directly, skipping the HTTP fetch (covered in test_auth)."""

    def __init__(self, key: rsa.RSAPrivateKey) -> None:
        self._keys = {
            k.key_id: k for k in jwt.PyJWKSet.from_dict(local_jwt.jwks(key.public_key())).keys
        }

    async def get_key(self, kid: str) -> jwt.PyJWK:
        try:
            return self._keys[kid]
        except KeyError:
            raise AuthError("unknown signing key") from None


def make_client(settings: Settings, key: rsa.RSAPrivateKey) -> httpx.AsyncClient:
    catalogue = load_catalogue(settings.catalogue_path)
    app = create_app(
        settings,
        jwks_source=StaticJwks(key),
        entitlements=LocalEntitlementProvider(PERSONAS),
        catalogue=catalogue,
        responder=MockResponder(catalogue),
        admin=build_mock_admin_service(frozenset(catalogue.modules), job_step_s=0),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test")


@pytest.fixture
def local_settings(tmp_path: Path, signing_key: rsa.RSAPrivateKey) -> Settings:
    local_jwt.write_private_key(signing_key, tmp_path)
    return Settings(env="local", keys_dir=tmp_path, cors_origins=[ORIGIN])


async def test_lists_personas(local_settings: Settings, signing_key: rsa.RSAPrivateKey) -> None:
    async with make_client(local_settings, signing_key) as c:
        r = await c.get("/dev/personas")
    assert r.json() == sorted(PERSONAS)


async def test_minted_token_round_trips_through_real_validation(
    local_settings: Settings, signing_key: rsa.RSAPrivateKey
) -> None:
    async with make_client(local_settings, signing_key) as c:
        r = await c.post("/dev/token", json={"persona": "sales_rep@globex"})
        assert r.status_code == 200
        assert r.json()["expires_in"] > 0
        me = await c.get("/me", headers={"Authorization": f"Bearer {r.json()['token']}"})
    assert me.status_code == 200
    assert me.json()["allowed_modules"] == ["contacts", "core", "deals"]


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"persona": "ceo@acme"}, 404),
        ({"persona": "sales_rep@globex", "modules": ["campaigns"]}, 422),
        ({}, 422),
    ],
)
async def test_rejects_unknown_or_extra(
    local_settings: Settings, signing_key: rsa.RSAPrivateKey, body: dict[str, object], status: int
) -> None:
    async with make_client(local_settings, signing_key) as c:
        assert (await c.post("/dev/token", json=body)).status_code == status


@pytest.mark.parametrize("env", ["test", "prod"])
async def test_dev_routes_absent_outside_local(env: str, signing_key: rsa.RSAPrivateKey) -> None:
    async with make_client(Settings(env=env), signing_key) as c:  # type: ignore[arg-type]
        assert (await c.get("/dev/personas")).status_code == 404
        assert (await c.post("/dev/token", json={"persona": "sales_rep@globex"})).status_code == 404


def preflight(origin: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    }


async def test_cors_allows_configured_origin(
    local_settings: Settings, signing_key: rsa.RSAPrivateKey
) -> None:
    async with make_client(local_settings, signing_key) as c:
        r = await c.options("/chat", headers=preflight(ORIGIN))
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-credentials" not in r.headers


async def test_cors_rejects_other_origin(
    local_settings: Settings, signing_key: rsa.RSAPrivateKey
) -> None:
    async with make_client(local_settings, signing_key) as c:
        r = await c.options("/chat", headers=preflight("https://evil.example"))
    assert "access-control-allow-origin" not in r.headers


async def test_cors_off_by_default(signing_key: rsa.RSAPrivateKey) -> None:
    async with make_client(Settings(env="test"), signing_key) as c:
        r = await c.options("/chat", headers=preflight(ORIGIN))
    assert "access-control-allow-origin" not in r.headers
