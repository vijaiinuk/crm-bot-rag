"""Admin access comes only from the verified token's admin_role; the server enforces it."""

from typing import Any

import httpx
import pytest

from tests.admin.conftest import AdminHeaders
from tests.conftest import MintToken

ROLES = ["viewer", "editor", "publisher"]

# (method, path, body, lowest role allowed). Bodies are valid enough to get past
# authorization; what happens after that is tested elsewhere.
ACTIONS: list[tuple[str, str, Any, str]] = [
    ("GET", "/admin/me", None, "viewer"),
    ("GET", "/admin/documents", None, "viewer"),
    ("GET", "/admin/documents/contacts-import", None, "viewer"),
    ("GET", "/admin/releases", None, "viewer"),
    ("GET", "/admin/releases/draft", None, "viewer"),
    ("GET", "/admin/releases/draft/diff", None, "viewer"),
    ("PUT", "/admin/releases/draft/documents/contacts-import", {"version": 3}, "editor"),
    ("DELETE", "/admin/releases/draft/documents/core-search-tips", None, "editor"),
    ("POST", "/admin/releases/r4/publish", None, "publisher"),
    ("POST", "/admin/releases/r4/confirm", None, "publisher"),
    ("POST", "/admin/releases/r2/rollback", None, "publisher"),
]


def allowed(role: str, minimum: str) -> bool:
    return ROLES.index(role) >= ROLES.index(minimum)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(
    ("method", "path", "body", "minimum"), ACTIONS, ids=[f"{m} {p}" for m, p, _, _ in ACTIONS]
)
async def test_role_matrix(
    admin_client: httpx.AsyncClient,
    admin_headers: AdminHeaders,
    role: str,
    method: str,
    path: str,
    body: Any,
    minimum: str,
) -> None:
    r = await admin_client.request(method, path, json=body, headers=admin_headers(role))
    if allowed(role, minimum):
        assert r.status_code != 403, r.text
        assert r.status_code < 500, r.text
    else:
        assert r.status_code == 403


@pytest.mark.parametrize("role", ["editor", "publisher"])
async def test_upload_allowed_for_editor_and_up(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders, role: str
) -> None:
    files = {
        "file": ("x.md", b"---\ndoc_id: x\ntitle: X\nmodules: [core]\n---\n# X\n", "text/markdown")
    }
    r = await admin_client.post("/admin/documents", files=files, headers=admin_headers(role))
    assert r.status_code == 201


async def test_upload_forbidden_for_viewer(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    files = {"file": ("x.md", b"---\ndoc_id: x\ntitle: X\nmodules: [core]\n---\n", "text/markdown")}
    r = await admin_client.post("/admin/documents", files=files, headers=admin_headers("viewer"))
    assert r.status_code == 403


async def test_me_reports_role(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    r = await admin_client.get("/admin/me", headers=admin_headers("editor"))
    assert r.json() == {"sub": "admin-editor", "admin_role": "editor"}


async def test_no_token_is_401(admin_client: httpx.AsyncClient) -> None:
    assert (await admin_client.get("/admin/documents")).status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {},  # an ordinary chat user's token
        {"tenant": "ops", "role": "ops_admin"},  # admin-shaped but no admin_role
        {"tenant": "ops", "role": "ops_admin", "extra_claims": {"admin_role": "superuser"}},
        {"tenant": "ops", "role": "ops_admin", "extra_claims": {"admin_role": ["publisher"]}},
        {"extra_claims": {"admin_role": "publisher"}},  # admin_role on a client-company token
    ],
    ids=["chat-token", "no-admin-role", "unknown-role", "non-string-role", "wrong-tenant"],
)
async def test_non_admin_tokens_are_403(
    admin_client: httpx.AsyncClient, mint: MintToken, overrides: dict[str, Any]
) -> None:
    r = await admin_client.get(
        "/admin/documents", headers={"Authorization": f"Bearer {mint(**overrides)}"}
    )
    assert r.status_code == 403


async def test_admin_token_cannot_chat(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    """ops_admin@ops is not a persona, so /chat fails closed."""
    r = await admin_client.post("/chat", json={"message": "hi"}, headers=admin_headers("publisher"))
    assert r.status_code == 403
