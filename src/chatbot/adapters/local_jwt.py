"""Local stand-in for the CRM identity provider: RSA keypair, JWKS, token minting.

Production validates tokens from the CRM's issuer; only key custody and minting
are local. Validation lives in chatbot.api.auth and is identical in both.
"""

import hashlib
import time
import uuid
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

PRIVATE_KEY_FILE = "private.pem"


def generate_private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def write_private_key(key: rsa.RSAPrivateKey, keys_dir: Path) -> Path:
    keys_dir.mkdir(parents=True, exist_ok=True)
    path = keys_dir / PRIVATE_KEY_FILE
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    path.chmod(0o600)
    return path


def load_private_key(keys_dir: Path) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key((keys_dir / PRIVATE_KEY_FILE).read_bytes(), None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise TypeError("expected an RSA private key")
    return key


def key_id(public_key: rsa.RSAPublicKey) -> str:
    der = public_key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(der).hexdigest()[:16]


def jwks(public_key: rsa.RSAPublicKey) -> dict[str, Any]:
    jwk: dict[str, Any] = jwt.algorithms.RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk |= {"kid": key_id(public_key), "use": "sig", "alg": "RS256"}
    return {"keys": [jwk]}


def mint_token(
    key: rsa.RSAPrivateKey,
    *,
    sub: str,
    tenant: str,
    role: str,
    issuer: str,
    audience: str,
    ttl_s: int = 3600,
    now: float | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    iat = int(now if now is not None else time.time())
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": sub,
        "tenant": tenant,
        "role": role,
        "iat": iat,
        "exp": iat + ttl_s,
        "jti": str(uuid.uuid4()),
    } | (extra_claims or {})
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": key_id(key.public_key())})
