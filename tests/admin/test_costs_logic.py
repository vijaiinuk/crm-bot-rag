from datetime import UTC, date, datetime

import pytest

from chatbot.admin.costs import cost_usd, summarize
from chatbot.admin.models import LlmCall, ModelPrice

PRICE = ModelPrice(
    price_id="p1",
    model_id="answer-medium",
    provider="placeholder",
    input_per_mtok=3.0,
    output_per_mtok=15.0,
    cached_input_per_mtok=0.3,
    valid_from=datetime(2026, 1, 1, tzinfo=UTC),
)


def call(**kw: object) -> LlmCall:
    base: dict[str, object] = {
        "id": "c",
        "trace_id": "t",
        "conversation_id": "conv-1",
        "tenant": "acme",
        "bucket": "chat",
        "stage": "generate",
        "model_id": "answer-medium",
        "provider": "placeholder",
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "price_id": "p1",
        "cost_usd": 0.0,
        "latency_ms": 100.0,
        "created_at": datetime(2026, 11, 10, 12, tzinfo=UTC),
    }
    return LlmCall.model_validate(base | kw)


def test_cost_usd_per_million_tokens() -> None:
    # 1M input at $3 + 0.5M output at $15 + 2M cached at $0.30
    assert cost_usd(1_000_000, 500_000, 2_000_000, PRICE) == pytest.approx(3 + 7.5 + 0.6)


def test_cost_usd_small_calls_keep_precision() -> None:
    assert cost_usd(1200, 300, 0, PRICE) == pytest.approx(0.0081)


def test_summarize_groups_by_bucket_tenant_model_day_and_conversation() -> None:
    calls = [
        call(id="1", cost_usd=1.0, tenant="acme", conversation_id="a1"),
        call(
            id="2",
            cost_usd=2.0,
            tenant="acme",
            conversation_id="a1",
            stage="rewrite",
            model_id="rewrite-small",
        ),
        call(id="3", cost_usd=4.0, tenant="globex", conversation_id="g1"),
        call(id="4", cost_usd=8.0, bucket="eval", stage="judge", tenant=None, conversation_id=None),
        call(
            id="5", cost_usd=16.0, bucket="ingest", stage="synth", tenant=None, conversation_id=None
        ),
        call(
            id="6", cost_usd=32.0, created_at=datetime(2026, 9, 1, tzinfo=UTC)
        ),  # outside the window
    ]
    s = summarize(calls, date(2026, 11, 1), date(2026, 11, 30))
    assert s.total_usd == pytest.approx(31.0)
    assert s.by_bucket == {
        "chat": pytest.approx(7.0),
        "eval": pytest.approx(8.0),
        "ingest": pytest.approx(16.0),
    }
    assert [(t.tenant, t.month, round(t.cost_usd, 6)) for t in s.by_tenant_month] == [
        ("acme", "2026-11", 3.0),
        ("globex", "2026-11", 4.0),
    ]
    assert {m.model_id: m.calls for m in s.by_model} == {"answer-medium": 4, "rewrite-small": 1}
    assert [(c.conversation_id, round(c.cost_usd, 6)) for c in s.top_conversations] == [
        ("g1", 4.0),
        ("a1", 3.0),
    ]
    (day,) = [d for d in s.daily if d.date == date(2026, 11, 10)]
    assert (round(day.chat, 6), round(day.eval, 6), round(day.ingest, 6)) == (7.0, 8.0, 16.0)
    assert len(s.daily) == 30, "every day in the window, zero-filled"


def test_internal_spend_is_never_billed_to_a_client() -> None:
    """Even if an eval row carries a tenant by mistake, it doesn't count against that client."""
    calls = [call(id="1", bucket="eval", stage="judge", tenant="acme", cost_usd=5.0)]
    s = summarize(calls, date(2026, 11, 1), date(2026, 11, 30))
    assert s.by_tenant_month == []
    assert s.by_bucket["eval"] == pytest.approx(5.0)
