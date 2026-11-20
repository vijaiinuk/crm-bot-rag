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
    Token,
    TokenUsage,
    Usage,
    WireEvent,
)
from chatbot.ports.entitlements import Principal
from chatbot.ports.responder import Query, Responder, Versions
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
    on_complete: Callable[[TraceRecord, str], None] | None = None,
) -> AsyncGenerator[WireEvent, None]:
    """`on_complete(trace, answer_text)` runs once after the trace is emitted, on
    every outcome. It must not raise; the answer may be partial or a refusal."""
    pin_failed = False
    try:
        versions = await responder.pin()
    except Exception:  # e.g. no live index: still a well-formed stream, ending in error
        log.exception("responder could not pin versions (trace_id=%s)", trace_id)
        versions = Versions("unavailable", "unavailable", "unavailable")
        pin_failed = True
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
    answer: list[str] = []
    try:
        yield Meta(
            trace_id=trace_id,
            conversation_id=query.conversation_id,
            index_version=versions.index_version,
            prompt_version=versions.prompt_version,
            model_id=versions.model_id,
        )
        if pin_failed:
            record.outcome = "error"
            yield GENERIC_ERROR
            return
        state: State = "start"
        usage = TokenUsage()
        refusal_kind = ""
        try:
            async with aclosing(
                responder.respond(query, principal, allowed_modules, versions)
            ) as events:
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
                        answer.append(event.message)
                    elif isinstance(event, Token):
                        answer.append(event.text)
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
        if on_complete is not None:
            try:
                on_complete(record, "".join(answer))
            except Exception:  # recording must never break the stream or hide the trace
                log.exception("on_complete failed (trace_id=%s)", trace_id)
