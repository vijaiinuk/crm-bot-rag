"""Chats are recorded server-side, redacted, costed, and owned by the user who started them."""

from typing import Any

import httpx

from tests.admin.conftest import AdminHeaders
from tests.conftest import MintToken, parse_sse

ANSWERED = "how do I move a deal to the next stage? I'm jane.doe@example.com"
RESTRICTED = "set up a triggered campaign email"


async def chat(
    client: httpx.AsyncClient, token: str, message: str, conversation_id: str | None = None
) -> httpx.Response:
    body: dict[str, Any] = {"message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id
    return await client.post("/chat", json=body, headers={"Authorization": f"Bearer {token}"})


def conversation_id_of(r: httpx.Response) -> str:
    meta = parse_sse(r.text)[0]
    assert meta[0] == "meta"
    return meta[1]["conversation_id"]  # type: ignore[no-any-return]


async def test_chat_is_recorded_redacted_and_costed(
    admin_client: httpx.AsyncClient, mint: MintToken, admin_headers: AdminHeaders
) -> None:
    rep = mint(sub="u-rep", tenant="globex", role="sales_rep")
    r = await chat(admin_client, rep, ANSWERED)
    conv = conversation_id_of(r)

    h = admin_headers("viewer")
    listed = (await admin_client.get("/admin/conversations?tenant=globex", headers=h)).json()
    (row,) = [c for c in listed if c["conversation_id"] == conv]
    assert (row["tenant"], row["sub"], row["role"], row["turns"]) == (
        "globex",
        "u-rep",
        "sales_rep",
        1,
    )
    assert row["cost_usd"] > 0

    detail = (await admin_client.get(f"/admin/conversations/{conv}", headers=h)).json()
    user_msg, bot_msg = detail["messages"]
    assert user_msg["role"] == "user" and "[email]" in user_msg["content"]
    assert "jane.doe" not in str(detail), "raw PII must never be stored"
    assert bot_msg["role"] == "assistant" and bot_msg["outcome"] == "answer"
    assert "Deals" in bot_msg["content"]
    (call,) = detail["llm_calls"]
    assert (call["bucket"], call["stage"], call["model_id"], call["tenant"]) == (
        "chat",
        "generate",
        "mock",
        "globex",
    )
    assert call["cost_usd"] == row["cost_usd"]


async def test_refusal_turn_costs_nothing(
    admin_client: httpx.AsyncClient, mint: MintToken, admin_headers: AdminHeaders
) -> None:
    """A templated refusal makes no LLM call, so it has no cost row."""
    rep = mint(sub="u-rep", tenant="globex", role="sales_rep")
    conv = conversation_id_of(await chat(admin_client, rep, RESTRICTED))
    detail = (
        await admin_client.get(f"/admin/conversations/{conv}", headers=admin_headers("viewer"))
    ).json()
    assert detail["llm_calls"] == []
    assert detail["messages"][1]["outcome"] == "refusal:restricted"


async def test_owner_can_continue_their_conversation(
    admin_client: httpx.AsyncClient, mint: MintToken, admin_headers: AdminHeaders
) -> None:
    token = mint(sub="u-1", tenant="acme", role="sales_manager")
    conv = conversation_id_of(await chat(admin_client, token, ANSWERED))
    r = await chat(admin_client, token, "and how do I add a stage?", conv)
    assert r.status_code == 200
    assert conversation_id_of(r) == conv
    detail = (
        await admin_client.get(f"/admin/conversations/{conv}", headers=admin_headers("viewer"))
    ).json()
    assert detail["turns"] == 2


async def test_someone_elses_conversation_is_404(
    admin_client: httpx.AsyncClient, mint: MintToken
) -> None:
    owner = mint(sub="u-1", tenant="acme", role="sales_manager")
    conv = conversation_id_of(await chat(admin_client, owner, ANSWERED))

    same_tenant_other_user = mint(sub="u-2", tenant="acme", role="sales_manager")
    other_tenant_same_sub = mint(sub="u-1", tenant="globex", role="sales_rep")
    for token in (same_tenant_other_user, other_tenant_same_sub):
        r = await chat(admin_client, token, "hi", conv)
        assert r.status_code == 404
        assert "event:" not in r.text, "no stream may start"


async def test_unknown_conversation_is_404(
    admin_client: httpx.AsyncClient, mint: MintToken
) -> None:
    r = await chat(admin_client, mint(), "hi", "7b0ad6a4-6c0e-4f3a-9a76-1f2d0c4e8b11")
    assert r.status_code == 404


async def test_conversations_list_filters_and_sorts(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    h = admin_headers("viewer")
    by_cost = (await admin_client.get("/admin/conversations?sort=cost&limit=10", headers=h)).json()
    assert len(by_cost) == 10
    costs = [c["cost_usd"] for c in by_cost]
    assert costs == sorted(costs, reverse=True)
    acme = (await admin_client.get("/admin/conversations?tenant=acme&limit=500", headers=h)).json()
    assert acme and {c["tenant"] for c in acme} == {"acme"}


async def test_seeded_transcripts_contain_no_raw_pii(
    admin_client: httpx.AsyncClient, admin_headers: AdminHeaders
) -> None:
    h = admin_headers("viewer")
    convs = (await admin_client.get("/admin/conversations?limit=500", headers=h)).json()
    for c in convs[:50]:
        detail = (
            await admin_client.get(f"/admin/conversations/{c['conversation_id']}", headers=h)
        ).json()
        assert "@example.com" not in str(detail)


async def test_conversations_need_admin(admin_client: httpx.AsyncClient, mint: MintToken) -> None:
    r = await admin_client.get(
        "/admin/conversations", headers={"Authorization": f"Bearer {mint()}"}
    )
    assert r.status_code == 403
