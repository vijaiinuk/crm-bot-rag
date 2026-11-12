from typing import Any

import httpx
import pytest

from tests.admin.conftest import AdminHeaders, wait_for_job

NEW_QUESTION: dict[str, Any] = {
    "question": "how do I share a dashboard with my team",
    "category": "single",
    "expected": {
        "sales_manager@acme": {
            "outcome": "answer",
            "required": ["reports-dashboards#share-a-dashboard"],
        },
        "sales_rep@globex": {"outcome": "restricted", "missing_modules": ["reports"]},
    },
}


async def questions(
    client: httpx.AsyncClient, h: dict[str, str], **params: str
) -> list[dict[str, Any]]:
    return (await client.get("/admin/eval-questions", params=params, headers=h)).json()  # type: ignore[no-any-return]


async def test_seeded_questions(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    h = admin_headers("viewer")
    accepted = await questions(admin_client, h, status="accepted")
    proposed = await questions(admin_client, h, status="proposed")
    assert len(accepted) >= 15
    assert len(proposed) == 5 and {q["source"] for q in proposed} == {"synthetic"}


async def test_create_question(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    r = await admin_client.post(
        "/admin/eval-questions", json=NEW_QUESTION, headers=admin_headers("editor")
    )
    assert r.status_code == 201
    q = r.json()
    assert (q["status"], q["source"], q["created_by"]) == ("accepted", "admin", "admin-editor")
    assert q["labels"] == ["reports-dashboards#share-a-dashboard"]


@pytest.mark.parametrize(
    "label",
    ["reports-dashboards#no-such-section", "no-such-doc#intro", "missing-hash"],
)
async def test_create_rejects_labels_that_dont_exist(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders, label: str
) -> None:
    body = NEW_QUESTION | {
        "expected": {"sales_manager@acme": {"outcome": "answer", "required": [label]}}
    }
    r = await admin_client.post("/admin/eval-questions", json=body, headers=admin_headers("editor"))
    assert r.status_code == 422


async def test_create_rejects_unknown_persona(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    body = NEW_QUESTION | {"expected": {"ceo@acme": {"outcome": "answer", "required": []}}}
    r = await admin_client.post("/admin/eval-questions", json=body, headers=admin_headers("editor"))
    assert r.status_code == 422


async def test_viewer_cannot_create(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    r = await admin_client.post(
        "/admin/eval-questions", json=NEW_QUESTION, headers=admin_headers("viewer")
    )
    assert r.status_code == 403


async def test_accept_and_reject_proposals(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    ed = admin_headers("editor")
    p1, p2, *_ = await questions(admin_client, ed, status="proposed")
    r = await admin_client.post(f"/admin/eval-questions/{p1['id']}/accept", headers=ed)
    assert (r.status_code, r.json()["status"]) == (200, "accepted")
    r = await admin_client.post(f"/admin/eval-questions/{p2['id']}/reject", headers=ed)
    assert (r.status_code, r.json()["status"]) == (200, "rejected")
    # Only proposals can be accepted or rejected.
    assert (
        await admin_client.post(f"/admin/eval-questions/{p1['id']}/reject", headers=ed)
    ).status_code == 409


async def test_fixing_an_orphaned_label_clears_the_gate_issue(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    """Seeded q-0001 points at deals-stage-automation#triggers, renamed in the draft."""
    ed = admin_headers("editor")
    q = (await admin_client.get("/admin/eval-questions/q-0001", headers=ed)).json()
    expected = q["expected"]
    for exp in expected.values():
        exp["required"] = [
            "deals-stage-automation#stage-triggers" if x.endswith("#triggers") else x
            for x in exp["required"]
        ]
    r = await admin_client.patch(
        "/admin/eval-questions/q-0001", json={"expected": expected}, headers=ed
    )
    assert r.status_code == 200, r.text
    diff = (await admin_client.get("/admin/releases/draft/diff", headers=ed)).json()
    assert diff["orphaned_labels"] == []


async def test_e2e_run_needs_publisher(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    assert (
        await admin_client.post("/admin/eval-runs", headers=admin_headers("editor"))
    ).status_code == 403


async def test_e2e_run_records_results_metrics_and_internal_cost(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    pub = admin_headers("publisher")
    before = (
        (await admin_client.get("/admin/costs?days=1", headers=pub))
        .json()["by_bucket"]
        .get("eval", 0)
    )
    r = await admin_client.post("/admin/eval-runs", headers=pub)
    assert r.status_code == 202
    job = await wait_for_job(admin_client, r.json()["job_id"], pub)
    assert job["status"] == "succeeded"

    run = (await admin_client.get(f"/admin/eval-runs/{r.json()['run_id']}", headers=pub)).json()
    assert run["status"] == "succeeded"
    assert run["started_by"] == "admin-publisher"
    assert run["results"], "one result per accepted question and persona"
    for metric in ("faithfulness", "correctness", "refusal_accuracy", "citation_accuracy"):
        assert 0 <= run["metrics"][metric] <= 1
    assert run["cost_usd"] > 0
    after = (await admin_client.get("/admin/costs?days=1", headers=pub)).json()["by_bucket"]["eval"]
    assert after == pytest.approx(before + run["cost_usd"])


async def test_labelling_updates_judge_agreement(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    ed = admin_headers("editor")
    runs = (await admin_client.get("/admin/eval-runs", headers=ed)).json()
    run = (await admin_client.get(f"/admin/eval-runs/{runs[0]['id']}", headers=ed)).json()
    unlabelled = [x for x in run["results"] if x["label"] is None]
    target = unlabelled[0]
    # Disagree with the judge on faithfulness, agree on correctness.
    label = {"faithful": not target["judge_faithful"], "correct": target["judge_correct"]}
    r = await admin_client.put(f"/admin/eval-results/{target['id']}/label", json=label, headers=ed)
    assert r.status_code == 200
    assert r.json()["label"]["labeller"] == "admin-editor"

    after = (await admin_client.get(f"/admin/eval-runs/{run['id']}", headers=ed)).json()
    before_n = run["judge_agreement"]["labelled"]
    assert after["judge_agreement"]["labelled"] == before_n + 1

    assert (
        await admin_client.put(
            f"/admin/eval-results/{target['id']}/label", json=label, headers=admin_headers("viewer")
        )
    ).status_code == 403


async def test_synthetic_generation_proposes_questions(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    ed = admin_headers("editor")
    before = {q["id"] for q in await questions(admin_client, ed, status="proposed")}
    r = await admin_client.post(
        "/admin/documents/reports-dashboards/synthetic-questions", headers=ed
    )
    assert r.status_code == 202
    await wait_for_job(admin_client, r.json()["job_id"], ed)
    new = [q for q in await questions(admin_client, ed, status="proposed") if q["id"] not in before]
    assert len(new) == 3
    for q in new:
        assert q["source"] == "synthetic"
        # Each persona either answers from this doc or is told reports is missing (the
        # test personas lack reports, so both are restricted here).
        for exp in q["expected"].values():
            assert exp["required"] == [] or all(
                x.startswith("reports-dashboards#") for x in exp["required"]
            )
            assert exp["outcome"] == "answer" or exp["missing_modules"] == ["reports"]
    costs = (await admin_client.get("/admin/costs?days=1", headers=ed)).json()
    assert costs["by_bucket"]["ingest"] > 0


async def test_synthetic_generation_for_unknown_doc_is_404(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    r = await admin_client.post(
        "/admin/documents/nope/synthetic-questions", headers=admin_headers("editor")
    )
    assert r.status_code == 404
