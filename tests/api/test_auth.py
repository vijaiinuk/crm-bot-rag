import base64
import hashlib
import hmac
import json
import time
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from chatbot.adapters import local_jwt
from chatbot.adapters.local_catalogue import load_catalogue
from chatbot.adapters.local_entitlements import LocalEntitlementProvider
from chatbot.adapters.mock_admin import build_mock_admin_service
from chatbot.adapters.mock_responder import MockResponder
from chatbot.api.app import create_app
from chatbot.config import Settings
from tests.conftest import AUDIENCE, ISSUER, MintToken


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def handmade_token(header: dict[str, Any], claims: dict[str, Any], secret: bytes = b"") -> str:
    signing_input = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(claims).encode())}"
    sig = b""
    if header["alg"] == "HS256":
        sig = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{b64(sig)}"


def valid_claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    return {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "u-1",
        "tenant": "acme",
        "role": "sales_manager",
        "iat": now,
        "exp": now + 600,
    } | overrides


# --- happy path -------------------------------------------------------------


async def test_valid_token_resolves_entitlements_server_side(
    client: httpx.AsyncClient, mint: MintToken
) -> None:
    r = await client.get("/me", headers=bearer(mint()))
    assert r.status_code == 200
    assert r.json() == {
        "sub": "u-1",
        "tenant": "acme",
        "role": "sales_manager",
        "allowed_modules": ["campaigns", "contacts", "core", "deals"],
    }


async def test_query_string_cannot_widen_entitlements(
    client: httpx.AsyncClient, mint: MintToken
) -> None:
    token = mint(tenant="globex", role="sales_rep")
    r = await client.get("/me?modules=campaigns&role=sales_manager", headers=bearer(token))
    assert r.status_code == 200
    assert "campaigns" not in r.json()["allowed_modules"]


async def test_jwks_is_cached(
    client: httpx.AsyncClient, mint: MintToken, jwks_state: dict[str, Any]
) -> None:
    for _ in range(3):
        assert (await client.get("/me", headers=bearer(mint()))).status_code == 200
    assert jwks_state["fetches"] == 1


# --- 401: token rejected ----------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic dXNlcjpwYXNz"}, {"Authorization": "Bearer not-a-jwt"}],
    ids=["missing", "wrong-scheme", "malformed"],
)
async def test_missing_or_malformed_credentials(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    r = await client.get("/me", headers=headers)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


async def test_expired_token(client: httpx.AsyncClient, mint: MintToken) -> None:
    token = mint(ttl_s=60, now=time.time() - 3600)
    assert (await client.get("/me", headers=bearer(token))).status_code == 401


@pytest.mark.parametrize("override", [{"audience": "other-app"}, {"issuer": "http://evil"}])
async def test_wrong_audience_or_issuer(
    client: httpx.AsyncClient, mint: MintToken, override: dict[str, str]
) -> None:
    assert (await client.get("/me", headers=bearer(mint(**override)))).status_code == 401


async def test_token_signed_by_unknown_key(
    client: httpx.AsyncClient, mint: MintToken, other_key: rsa.RSAPrivateKey
) -> None:
    assert (await client.get("/me", headers=bearer(mint(key=other_key)))).status_code == 401


async def test_forged_signature_with_trusted_kid(
    client: httpx.AsyncClient, signing_key: rsa.RSAPrivateKey, other_key: rsa.RSAPrivateKey
) -> None:
    kid = local_jwt.key_id(signing_key.public_key())
    token = jwt.encode(valid_claims(), other_key, algorithm="RS256", headers={"kid": kid})
    assert (await client.get("/me", headers=bearer(token))).status_code == 401


@pytest.mark.parametrize("missing", ["tenant", "role", "sub", "exp", "iss", "aud"])
async def test_missing_required_claim(
    client: httpx.AsyncClient, signing_key: rsa.RSAPrivateKey, missing: str
) -> None:
    claims = valid_claims()
    del claims[missing]
    kid = local_jwt.key_id(signing_key.public_key())
    token = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": kid})
    assert (await client.get("/me", headers=bearer(token))).status_code == 401


@pytest.mark.parametrize("bad", [{"tenant": ""}, {"role": 123}, {"tenant": ["acme"]}])
async def test_malformed_identity_claim(
    client: httpx.AsyncClient, signing_key: rsa.RSAPrivateKey, bad: dict[str, Any]
) -> None:
    kid = local_jwt.key_id(signing_key.public_key())
    token = jwt.encode(valid_claims(**bad), signing_key, algorithm="RS256", headers={"kid": kid})
    assert (await client.get("/me", headers=bearer(token))).status_code == 401


async def test_alg_none_rejected(client: httpx.AsyncClient, signing_key: rsa.RSAPrivateKey) -> None:
    kid = local_jwt.key_id(signing_key.public_key())
    token = handmade_token({"alg": "none", "typ": "JWT", "kid": kid}, valid_claims())
    assert (await client.get("/me", headers=bearer(token))).status_code == 401


async def test_hs256_key_confusion_rejected(
    client: httpx.AsyncClient, signing_key: rsa.RSAPrivateKey
) -> None:
    """Classic attack: HMAC-sign with the *public* key, hoping the verifier uses it as a secret."""
    public_pem = signing_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    kid = local_jwt.key_id(signing_key.public_key())
    token = handmade_token({"alg": "HS256", "typ": "JWT", "kid": kid}, valid_claims(), public_pem)
    assert (await client.get("/me", headers=bearer(token))).status_code == 401


# --- 403 / 503: valid identity, entitlements unavailable --------------------


async def test_unknown_persona_is_denied(client: httpx.AsyncClient, mint: MintToken) -> None:
    r = await client.get("/me", headers=bearer(mint(role="ceo")))
    assert r.status_code == 403
    assert "allowed_modules" not in r.text


async def test_unreachable_jwks_fails_closed(
    client: httpx.AsyncClient, mint: MintToken, jwks_state: dict[str, Any]
) -> None:
    jwks_state["fail"] = True
    r = await client.get("/me", headers=bearer(mint()))
    assert r.status_code == 503
    assert "allowed_modules" not in r.text


# --- local JWKS endpoint and app wiring -------------------------------------


def _app_client(settings: Settings) -> httpx.AsyncClient:
    catalogue = load_catalogue(settings.catalogue_path)
    app = create_app(
        settings,
        entitlements=LocalEntitlementProvider({}),
        catalogue=catalogue,
        responder=MockResponder(catalogue),
        admin=build_mock_admin_service(frozenset(catalogue.modules), job_step_s=0),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test")


async def test_local_env_serves_jwks(tmp_path: Any, signing_key: rsa.RSAPrivateKey) -> None:
    local_jwt.write_private_key(signing_key, tmp_path)
    async with _app_client(Settings(env="local", keys_dir=tmp_path)) as c:
        r = await c.get("/.well-known/jwks.json")
    assert r.status_code == 200
    assert r.json() == local_jwt.jwks(signing_key.public_key())
    assert "d" not in r.json()["keys"][0], "private exponent must never be published"


@pytest.mark.parametrize("env", ["test", "prod"])
async def test_jwks_endpoint_only_in_local(env: str) -> None:
    async with _app_client(Settings(env=env)) as c:  # type: ignore[arg-type]
        assert (await c.get("/.well-known/jwks.json")).status_code == 404


def test_prod_without_entitlement_provider_refuses_to_start() -> None:
    with pytest.raises(RuntimeError, match="entitlement provider"):
        create_app(Settings(env="prod"))


def test_prod_without_admin_repository_refuses_to_start() -> None:
    catalogue = load_catalogue(Settings().catalogue_path)
    with pytest.raises(RuntimeError, match="admin repository"):
        create_app(
            Settings(env="prod"),
            entitlements=LocalEntitlementProvider({}),
            responder=MockResponder(catalogue),
        )


def test_prod_without_responder_refuses_to_start() -> None:
    with pytest.raises(RuntimeError, match="responder"):
        create_app(Settings(env="prod"), entitlements=LocalEntitlementProvider({}))
