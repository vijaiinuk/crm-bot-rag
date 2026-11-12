import httpx
import pytest

from tests.admin.conftest import AdminHeaders

VALID = b"""---
doc_id: core-keyboard-shortcuts
title: Keyboard shortcuts
modules: [core]
---
# Keyboard shortcuts

## Global shortcuts

Press `?` anywhere to see them.
"""


async def upload(
    client: httpx.AsyncClient, headers: dict[str, str], content: bytes, name: str = "doc.md"
) -> httpx.Response:
    return await client.post(
        "/admin/documents", files={"file": (name, content, "text/markdown")}, headers=headers
    )


async def test_upload_new_doc(admin_client: httpx.AsyncClient, admin_headers: AdminHeaders) -> None:
    r = await upload(admin_client, admin_headers("editor"), VALID)
    assert r.status_code == 201
    v = r.json()
    assert (v["doc_id"], v["version"], v["status"]) == ("core-keyboard-shortcuts", 1, "validated")
    assert v["modules"] == ["core"]
    assert v["anchors"] == ["keyboard-shortcuts", "global-shortcuts"]
    assert v["uploaded_by"] == "admin-editor"
    assert v["validation_errors"] == []

    detail = (
        await admin_client.get(
            "/admin/documents/core-keyboard-shortcuts", headers=admin_headers("viewer")
        )
    ).json()
    assert [x["version"] for x in detail["versions"]] == [1]
    assert detail["live_version"] is None, "nothing is live until a release is published"


async def test_reupload_increments_version(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    before = (
        await admin_client.get("/admin/documents/contacts-import", headers=admin_headers("viewer"))
    ).json()
    content = (
        b"---\ndoc_id: contacts-import\ntitle: Importing contacts\n"
        b"modules: [contacts]\n---\n# Import\n"
    )
    r = await upload(admin_client, admin_headers("editor"), content)
    assert r.json()["version"] == before["latest_version"] + 1


@pytest.mark.parametrize(
    ("content", "error"),
    [
        (b"---\ndoc_id: x\ntitle: X\nmodules: [dealz]\n---\n# X\n", "unknown module"),
        (b"---\ndoc_id: x\ntitle: X\nmodules: []\n---\n# X\n", "modules"),
        (b"---\ndoc_id: x\ntitle: X\n---\n# X\n", "modules"),
        (b"---\ndoc_id: x\nmodules: [core]\n---\n# X\n", "title"),
    ],
    ids=["unknown-module", "empty-modules", "missing-modules", "missing-title"],
)
async def test_invalid_frontmatter_is_stored_as_rejected(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders, content: bytes, error: str
) -> None:
    """The doc_id is known, so the attempt is kept in its history with the reasons."""
    r = await upload(admin_client, admin_headers("editor"), content)
    assert r.status_code == 201
    v = r.json()
    assert v["status"] == "rejected"
    assert any(error in e for e in v["validation_errors"]), v["validation_errors"]


@pytest.mark.parametrize(
    ("content", "name"),
    [
        (b"# No frontmatter at all\n", "doc.md"),
        (b"---\ntitle: X\nmodules: [core]\n---\n", "doc.md"),
        (b"---\ndoc_id: Not A Slug\ntitle: X\nmodules: [core]\n---\n", "doc.md"),
        (b"---\n[unclosed\n---\n", "doc.md"),
        (b"\xff\xfe\x00bad", "doc.md"),
        (VALID, "doc.pdf"),
        (b"---\ndoc_id: x\ntitle: X\nmodules: [core]\n---\n" + b"a" * 600_000, "doc.md"),
    ],
    ids=[
        "no-frontmatter",
        "no-doc-id",
        "bad-doc-id",
        "bad-yaml",
        "not-utf8",
        "not-markdown",
        "too-large",
    ],
)
async def test_unidentifiable_upload_is_422(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders, content: bytes, name: str
) -> None:
    """Without a valid doc_id there is no document to attach the attempt to."""
    r = await upload(admin_client, admin_headers("editor"), content, name)
    assert r.status_code == 422
    assert r.json()["detail"]


async def test_rejected_version_cannot_enter_draft(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    bad = b"---\ndoc_id: contacts-import\ntitle: X\nmodules: [dealz]\n---\n# X\n"
    v = (await upload(admin_client, admin_headers("editor"), bad)).json()
    r = await admin_client.put(
        "/admin/releases/draft/documents/contacts-import",
        json={"version": v["version"]},
        headers=admin_headers("editor"),
    )
    assert r.status_code == 409


async def test_unknown_document_is_404(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    assert (
        await admin_client.get("/admin/documents/nope", headers=admin_headers("viewer"))
    ).status_code == 404


async def test_staleness(admin_client: httpx.AsyncClient, admin_headers: AdminHeaders) -> None:
    h = admin_headers("viewer")
    docs = (await admin_client.get("/admin/documents", headers=h)).json()
    stale = {d["doc_id"] for d in docs if d["stale"]}
    assert stale == {"contacts-merge-duplicates", "reports-scheduled-exports"}, (
        "seeded as 120 and 200 days old"
    )
    docs = (await admin_client.get("/admin/documents?stale_days=150", headers=h)).json()
    assert {d["doc_id"] for d in docs if d["stale"]} == {"reports-scheduled-exports"}
    docs = (await admin_client.get("/admin/documents?stale_days=1000", headers=h)).json()
    assert not any(d["stale"] for d in docs)
