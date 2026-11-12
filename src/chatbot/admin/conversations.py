"""Pure: turn a recorded chat turn into message and cost rows."""

from collections.abc import Callable

from chatbot.admin.costs import cost_usd
from chatbot.admin.models import LlmCall, Message, ModelPrice
from chatbot.ports.conversations import ChatTurn


def turn_rows(
    turn: ChatTurn, price: ModelPrice | None, next_id: Callable[[str], str]
) -> tuple[list[Message], list[LlmCall]]:
    t = turn.trace
    messages = [
        Message(
            id=next_id("msg"),
            conversation_id=t.conversation_id,
            trace_id=t.trace_id,
            role="user",
            content=turn.question,
            created_at=turn.at,
        ),
        Message(
            id=next_id("msg"),
            conversation_id=t.conversation_id,
            trace_id=t.trace_id,
            role="assistant",
            content=turn.answer,
            outcome=t.outcome,
            created_at=turn.at,
        ),
    ]
    calls = []
    # Templated refusals make no LLM call, so they have no tokens and no cost row.
    if (t.input_tokens or t.output_tokens) and price is not None:
        calls.append(
            LlmCall(
                id=next_id("call"),
                trace_id=t.trace_id,
                conversation_id=t.conversation_id,
                tenant=t.tenant,
                bucket="chat",
                stage="generate",
                model_id=t.model_id,
                provider=price.provider,
                input_tokens=t.input_tokens,
                output_tokens=t.output_tokens,
                price_id=price.price_id,
                cost_usd=cost_usd(t.input_tokens, t.output_tokens, 0, price),
                latency_ms=t.latency_ms,
                created_at=turn.at,
            )
        )
    return messages, calls
