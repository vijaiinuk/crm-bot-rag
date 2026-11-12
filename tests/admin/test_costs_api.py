import httpx
import pytest

from tests.admin.conftest import AdminHeaders


async def test_cost_summary_shape(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    s = (await admin_client.get("/admin/costs?days=60", headers=admin_headers("viewer"))).json()
    assert len(s["daily"]) == 60
    assert set(s["by_bucket"]) == {"chat", "eval", "ingest"}
    assert {t["tenant"] for t in s["by_tenant_month"]} == {"acme", "globex"}
    assert s["total_usd"] == pytest.approx(sum(s["by_bucket"].values()))
    assert s["top_conversations"] and s["by_model"]
    assert s["estimated"] is True


async def test_session_cost_matches_its_calls(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    h = admin_headers("viewer")
    top = (await admin_client.get("/admin/costs?days=60", headers=h)).json()["top_conversations"][0]
    detail = (
        await admin_client.get(f"/admin/conversations/{top['conversation_id']}", headers=h)
    ).json()
    assert sum(c["cost_usd"] for c in detail["llm_calls"]) == pytest.approx(top["cost_usd"])


async def test_prices_are_labelled_placeholders(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    prices = (await admin_client.get("/admin/prices", headers=admin_headers("viewer"))).json()
    assert {p["model_id"] for p in prices} >= {
        "mock",
        "rewrite-small",
        "answer-medium",
        "judge-large",
    }
    assert all(p["provider"] == "placeholder" for p in prices)


async def test_days_is_bounded(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    h = admin_headers("viewer")
    assert (await admin_client.get("/admin/costs?days=0", headers=h)).status_code == 422
    assert (await admin_client.get("/admin/costs?days=400", headers=h)).status_code == 422


async def test_overview(admin_client: httpx.AsyncClient, admin_headers: AdminHeaders) -> None:
    o = (await admin_client.get("/admin/overview", headers=admin_headers("viewer"))).json()
    assert o["live_release"]["id"] == "r3"
    assert o["draft_release"]["id"] == "r4"
    assert o["documents"] == 13 and o["stale_documents"] == 2
    assert o["proposed_questions"] == 5
    assert o["month_to_date_usd"] >= 0
    assert o["conversations_7d"] > 0
