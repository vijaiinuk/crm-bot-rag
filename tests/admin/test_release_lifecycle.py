"""Release lifecycle against the seeded mock data.

Seed: r1, r2 superseded; r3 live; draft r4 contains
  - deals-forecasting v2: modules [deals, reports] -> [reports]   (widens access)
  - deals-stage-automation v3: heading "Triggers" renamed          (orphans an eval label)
  - core-search-tips v1: a new doc
"""

import httpx
import pytest

from chatbot.api.auth import HttpJwksSource
from chatbot.config import Settings
from tests.admin.conftest import AdminHeaders, make_admin_client, wait_for_job


async def live_id(client: httpx.AsyncClient, h: dict[str, str]) -> str:
    releases = (await client.get("/admin/releases", headers=h)).json()
    (live,) = [r["id"] for r in releases if r["status"] == "live"]
    return live  # type: ignore[no-any-return]


async def publish(client: httpx.AsyncClient, h: dict[str, str]) -> dict:  # type: ignore[type-arg]
    draft = (await client.get("/admin/releases/draft", headers=h)).json()
    r = await client.post(f"/admin/releases/{draft['id']}/publish", headers=h)
    assert r.status_code == 202, r.text
    job = await wait_for_job(client, r.json()["job_id"], h)
    assert job["status"] == "succeeded", job
    return (await client.get(f"/admin/releases/{draft['id']}", headers=h)).json()  # type: ignore[no-any-return]


async def test_seeded_state(admin_client: httpx.AsyncClient, admin_headers: AdminHeaders) -> None:
    h = admin_headers("viewer")
    releases = {
        r["id"]: r["status"] for r in (await admin_client.get("/admin/releases", headers=h)).json()
    }
    assert releases == {"r1": "superseded", "r2": "superseded", "r3": "live", "r4": "draft"}


async def test_draft_diff_preview(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    diff = (
        await admin_client.get("/admin/releases/draft/diff", headers=admin_headers("viewer"))
    ).json()
    changes = {
        c["doc_id"]: c["change"] for c in diff["module_changes"] if c["change"] != "unchanged"
    }
    assert changes == {"deals-forecasting": "widened", "core-search-tips": "new"}
    assert [o["label"] for o in diff["orphaned_labels"]] == ["deals-stage-automation#triggers"]


async def test_full_lifecycle(admin_client: httpx.AsyncClient, admin_headers: AdminHeaders) -> None:
    pub, editor = admin_headers("publisher"), admin_headers("editor")

    # 1. The seeded draft fails the gate on the orphaned label; live is untouched.
    r4 = await publish(admin_client, pub)
    assert r4["status"] == "failed"
    checks = {c["name"]: c["status"] for c in r4["gate_report"]["checks"]}
    assert checks["orphaned_labels"] == "fail"
    assert checks["permission_suite"] == "pass"
    assert checks["access_widening"] == "needs_confirmation"
    assert r4["published_by"] == "admin-publisher"
    assert await live_id(admin_client, pub) == "r3"

    # 2. A fresh draft carries the same docs; the editor pins the old version back.
    draft = (await admin_client.get("/admin/releases/draft", headers=editor)).json()
    assert draft["id"] == "r5"
    assert draft["documents"] == r4["documents"]
    r = await admin_client.put(
        "/admin/releases/draft/documents/deals-stage-automation",
        json={"version": 2},
        headers=editor,
    )
    assert r.status_code == 200

    # 3. Now the only issue is widening: the release waits for a publisher.
    r5 = await publish(admin_client, pub)
    assert r5["status"] == "awaiting_confirmation"
    assert await live_id(admin_client, pub) == "r3"
    assert (
        await admin_client.post("/admin/releases/r5/confirm", headers=editor)
    ).status_code == 403

    r = await admin_client.post("/admin/releases/r5/confirm", headers=pub)
    assert r.status_code == 200
    assert r.json()["status"] == "live"
    assert r.json()["confirmed_by"] == "admin-publisher"
    assert await live_id(admin_client, pub) == "r5"

    doc = (await admin_client.get("/admin/documents/deals-forecasting", headers=pub)).json()
    assert doc["live_version"] == 2

    # 4. Roll back to r3: r3 is live again, r5 superseded.
    r = await admin_client.post("/admin/releases/r3/rollback", headers=pub)
    assert r.status_code == 200
    statuses = {
        x["id"]: x["status"]
        for x in (await admin_client.get("/admin/releases", headers=pub)).json()
    }
    assert statuses["r3"] == "live" and statuses["r5"] == "superseded"
    doc = (await admin_client.get("/admin/documents/deals-forecasting", headers=pub)).json()
    assert doc["live_version"] == 1


async def test_clean_draft_goes_straight_live(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    pub, editor = admin_headers("publisher"), admin_headers("editor")
    # Make the draft identical to live except for the new doc: no widening, no orphans.
    for doc_id, version in (("deals-forecasting", 1), ("deals-stage-automation", 2)):
        r = await admin_client.put(
            f"/admin/releases/draft/documents/{doc_id}", json={"version": version}, headers=editor
        )
        assert r.status_code == 200
    r4 = await publish(admin_client, pub)
    assert r4["status"] == "live"
    assert await live_id(admin_client, pub) == "r4"


async def test_removing_doc_from_draft_retires_it(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    editor = admin_headers("editor")
    r = await admin_client.delete(
        "/admin/releases/draft/documents/reports-scheduled-exports", headers=editor
    )
    assert r.status_code == 200
    diff = (await admin_client.get("/admin/releases/draft/diff", headers=editor)).json()
    retired = [c["doc_id"] for c in diff["module_changes"] if c["change"] == "retired"]
    assert retired == ["reports-scheduled-exports"]


@pytest.mark.parametrize(
    ("action", "release_id", "status"),
    [
        ("publish", "r3", 409),  # only the draft can be published
        ("confirm", "r4", 409),  # nothing is awaiting confirmation
        ("rollback", "r4", 409),  # the draft was never live
        ("rollback", "r3", 409),  # already live
        ("publish", "r99", 404),
    ],
)
async def test_invalid_transitions(
    admin_client: httpx.AsyncClient,
    admin_headers: AdminHeaders,
    action: str,
    release_id: str,
    status: int,
) -> None:
    r = await admin_client.post(
        f"/admin/releases/{release_id}/{action}", headers=admin_headers("publisher")
    )
    assert r.status_code == status


async def test_cannot_roll_back_to_a_failed_release(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    pub = admin_headers("publisher")
    assert (await publish(admin_client, pub))["status"] == "failed"
    assert (await admin_client.post("/admin/releases/r4/rollback", headers=pub)).status_code == 409


async def test_unknown_draft_version_is_404(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    r = await admin_client.put(
        "/admin/releases/draft/documents/contacts-import",
        json={"version": 99},
        headers=admin_headers("editor"),
    )
    assert r.status_code == 404


async def test_one_build_at_a_time(
    settings: Settings, jwks_source: HttpJwksSource, admin_headers: AdminHeaders
) -> None:
    slow = settings.model_copy(update={"mock_job_step_s": 0.2})
    async for client in make_admin_client(slow, jwks_source):
        pub = admin_headers("publisher")
        first = await client.post("/admin/releases/r4/publish", headers=pub)
        assert first.status_code == 202
        draft = (await client.get("/admin/releases/draft", headers=pub)).json()
        second = await client.post(f"/admin/releases/{draft['id']}/publish", headers=pub)
        assert second.status_code == 409
        job = (await client.get(f"/admin/jobs/{first.json()['job_id']}", headers=pub)).json()
        assert job["status"] in ("queued", "running")
        assert 0 <= job["progress"]["pct"] <= 100
        await wait_for_job(client, first.json()["job_id"], pub)
