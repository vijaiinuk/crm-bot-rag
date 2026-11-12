"""Pure cost maths: price a call, aggregate calls for the dashboard."""

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta

from chatbot.admin.models import (
    ConversationCost,
    CostSummary,
    DailyCost,
    LlmCall,
    ModelCost,
    ModelPrice,
    TenantMonth,
)

BUCKETS = ("chat", "eval", "ingest")
TOP_CONVERSATIONS = 10


def cost_usd(
    input_tokens: int, output_tokens: int, cached_input_tokens: int, price: ModelPrice
) -> float:
    """Estimated cost. `input_tokens` excludes cached ones, which bill at the cached rate."""
    return round(
        (
            input_tokens * price.input_per_mtok
            + output_tokens * price.output_per_mtok
            + cached_input_tokens * price.cached_input_per_mtok
        )
        / 1_000_000,
        8,
    )


def summarize(calls: Iterable[LlmCall], start: date, end: date) -> CostSummary:
    """Aggregate calls created between start and end (inclusive, UTC dates).

    Only the `chat` bucket is attributed to client companies; eval and ingest
    spend is internal even if a row carries a tenant.
    """
    window = [c for c in calls if start <= c.created_at.date() <= end]

    by_bucket = dict.fromkeys(BUCKETS, 0.0)
    tenant_month: dict[tuple[str, str], list[float]] = defaultdict(list)
    models: dict[str, ModelCost] = {}
    daily = {
        start + timedelta(days=i): dict.fromkeys(BUCKETS, 0.0)
        for i in range((end - start).days + 1)
    }
    per_conversation: dict[str, tuple[str | None, float]] = {}

    for c in window:
        by_bucket[c.bucket] += c.cost_usd
        daily[c.created_at.date()][c.bucket] += c.cost_usd
        m = models.setdefault(
            c.model_id,
            ModelCost(model_id=c.model_id, calls=0, input_tokens=0, output_tokens=0, cost_usd=0.0),
        )
        m.calls += 1
        m.input_tokens += c.input_tokens + c.cached_input_tokens
        m.output_tokens += c.output_tokens
        m.cost_usd += c.cost_usd
        if c.bucket == "chat" and c.tenant:
            tenant_month[(c.tenant, c.created_at.strftime("%Y-%m"))].append(c.cost_usd)
            if c.conversation_id:
                _, total = per_conversation.get(c.conversation_id, (c.tenant, 0.0))
                per_conversation[c.conversation_id] = (c.tenant, total + c.cost_usd)

    top = sorted(per_conversation.items(), key=lambda kv: kv[1][1], reverse=True)[
        :TOP_CONVERSATIONS
    ]
    return CostSummary(
        start=start,
        end=end,
        total_usd=round(sum(by_bucket.values()), 8),
        by_bucket={k: round(v, 8) for k, v in by_bucket.items()},
        by_tenant_month=[
            TenantMonth(tenant=t, month=mo, cost_usd=round(sum(v), 8), calls=len(v))
            for (t, mo), v in sorted(tenant_month.items())
        ],
        by_model=sorted(models.values(), key=lambda m: m.cost_usd, reverse=True),
        daily=[
            DailyCost(
                date=d,
                chat=round(v["chat"], 8),
                eval=round(v["eval"], 8),
                ingest=round(v["ingest"], 8),
            )
            for d, v in daily.items()
        ],
        top_conversations=[
            ConversationCost(conversation_id=cid, tenant=t, cost_usd=round(v, 8))
            for cid, (t, v) in top
        ],
    )
