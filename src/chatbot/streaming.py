"""Wraps any Responder so the client always sees a well-formed event stream.

The responder supplies content; this module owns `meta`, the terminal event,
ordering, error masking and the trace. A responder that misbehaves produces
an `error` event, never a malformed stream.
"""

import logging
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from typing import Literal

from chatbot.events import (
    Done,
    ErrorEvent,
    Meta,
    Refusal,
    TokenUsage,
    Usage,
    WireEvent,
)
from chatbot.ports.entitlements import Principal
from chatbot.ports.responder import Query, Responder
from chatbot.tracing.log import TraceRecord, emit_trace

log = logging.getLogger(__name__)

GENERIC_ERROR = ErrorEvent(code="internal", message="Something went wrong. Please try again.")

State = Literal["start", "answering", "cited", "refused"]

# state -> event type -> next state. Anything absent is a protocol violation.
_TRANSITIONS: dict[State, dict[str, State]] = {
    "start": {"token": "answering", "refusal": "refused"},
    "answering": {"token": "answering", "citations": "cited"},
    "cited": {},
    "refused": {},
}


class ProtocolViolation(Exception):
    pass


async def stream_events(
    responder: Responder,
    query: Query,
    principal: Principal,
    allowed_modules: frozenset[str],
    *,
    trace_id: str,
    emit: Callable[[TraceRecord], None] = emit_trace,
) -> AsyncGenerator[WireEvent, None]:
    versions = responder.versions
    record = TraceRecord(
        trace_id=trace_id,
        conversation_id=query.conversation_id,
        sub=principal.sub,
        tenant=principal.tenant,
        role=principal.role,
        allowed_modules=sorted(allowed_modules),
        index_version=versions.index_version,
        prompt_version=versions.prompt_version,
        model_id=versions.model_id,
        message_chars=len(query.message),
    )
    started = time.perf_counter()
    try:
        yield Meta(
            trace_id=trace_id,
            conversation_id=query.conversation_id,
            index_version=versions.index_version,
            prompt_version=versions.prompt_version,
            model_id=versions.model_id,
        )
        state: State = "start"
        usage = TokenUsage()
        refusal_kind = ""
        try:
            async with aclosing(responder.respond(query, principal, allowed_modules)) as events:
                async for event in events:
                    if isinstance(event, Usage):
                        usage = event.usage
                        continue
                    next_state = _TRANSITIONS[state].get(event.type)
                    if next_state is None:
                        raise ProtocolViolation(f"{event.type} not allowed in state {state}")
                    state = next_state
                    if isinstance(event, Refusal):
                        refusal_kind = event.kind
                    yield event
            if state == "start":
                raise ProtocolViolation("responder produced no content")
        except Exception:
            log.exception("responder failed (trace_id=%s)", trace_id)
            record.outcome = "error"
            yield GENERIC_ERROR
            return

        record.input_tokens = usage.input_tokens
        record.output_tokens = usage.output_tokens
        record.outcome = f"refusal:{refusal_kind}" if state == "refused" else "answer"
        yield Done(usage=usage)
    finally:
        # Runs on success, error and client disconnect (GeneratorExit/CancelledError).
        record.latency_ms = round((time.perf_counter() - started) * 1000, 1)
        emit(record)
