import json
import logging
from typing import Any

import httpx
import pytest

from tests.conftest import MintToken, parse_sse

QUESTION = "how do I email contacts when a deal changes stage"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def chat(client: httpx.AsyncClient, token: str, body: dict[str, Any]) -> httpx.Response:
    return await client.post("/chat", json=body, headers=bearer(token))


async def test_requires_token(client: httpx.AsyncClient) -> None:
    r = await client.post("/chat", json={"message": QUESTION})
    assert r.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"message": QUESTION, "modules": ["campaigns"]},
        {"message": QUESTION, "role": "sales_manager"},
        {"message": QUESTION, "tenant": "acme"},
        {"message": QUESTION, "anything": 1},
        {"message": "   "},
        {"message": "x" * 2001},
        {"message": QUESTION, "conversation_id": "not-a-uuid"},
        {},
    ],
    ids=["modules", "role", "tenant", "unknown-field", "blank", "too-long", "bad-conv-id", "empty"],
)
async def test_rejects_bad_bodies(
    client: httpx.AsyncClient, mint: MintToken, body: dict[str, Any]
) -> None:
    """Entitlement-shaped fields in the body are rejected outright (rule 1)."""
    assert (await chat(client, mint(), body)).status_code == 422


async def test_answer_stream(client: httpx.AsyncClient, mint: MintToken) -> None:
    r = await chat(client, mint(), {"message": QUESTION})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    events = parse_sse(r.text)
    names = [name for name, _ in events]
    assert names[0] == "meta" and names[-2:] == ["citations", "done"]
    assert set(names[1:-2]) == {"token"}
    meta = events[0][1]
    assert meta["index_version"] == meta["prompt_version"] == meta["model_id"] == "mock"
    assert "type" not in meta, "the event name carries the type"


async def test_conversation_id_is_echoed(client: httpx.AsyncClient, mint: MintToken) -> None:
    conv = "7b0ad6a4-6c0e-4f3a-9a76-1f2d0c4e8b11"
    r = await chat(client, mint(), {"message": QUESTION, "conversation_id": conv})
    assert parse_sse(r.text)[0][1]["conversation_id"] == conv


async def test_restricted_stream(client: httpx.AsyncClient, mint: MintToken) -> None:
    r = await chat(client, mint(tenant="globex", role="sales_rep"), {"message": QUESTION})
    events = parse_sse(r.text)
    assert [name for name, _ in events] == ["meta", "refusal", "done"]
    refusal = events[1][1]
    assert refusal["kind"] == "restricted"
    assert refusal["missing_modules"] == ["campaigns"]
    assert "Campaigns" in refusal["message"]


async def test_error_stream(client: httpx.AsyncClient, mint: MintToken) -> None:
    r = await chat(client, mint(), {"message": "simulate:error"})
    assert r.status_code == 200, "the stream had already started"
    names = [name for name, _ in parse_sse(r.text)]
    assert names[0] == "meta" and names[-1] == "error"
    assert "done" not in names


async def test_trace_logged_without_question_text(
    client: httpx.AsyncClient, mint: MintToken, caplog: pytest.LogCaptureFixture
) -> None:
    secret_question = "how do deals relate to jane.doe@example.com"
    with caplog.at_level(logging.INFO, logger="chatbot.trace"):
        await chat(client, mint(tenant="globex", role="sales_rep"), {"message": secret_question})
    (line,) = [r.getMessage() for r in caplog.records if r.name == "chatbot.trace"]
    trace = json.loads(line)
    assert trace["allowed_modules"] == ["contacts", "core", "deals"]
    assert (trace["tenant"], trace["role"]) == ("globex", "sales_rep")
    assert trace["outcome"] == "answer"
    assert trace["model_id"] == "mock"
    assert "jane.doe" not in line
    assert trace["message_chars"] == len(secret_question)
