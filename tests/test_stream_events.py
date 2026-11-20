"""Event-order invariants hold for ANY responder, not just the mock."""

from collections.abc import AsyncGenerator, Sequence

from chatbot.events import (
    Citation,
    Citations,
    ContentEvent,
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
from chatbot.ports.responder import Query, Versions
from chatbot.streaming import stream_events
from chatbot.tracing.log import TraceRecord

PRINCIPAL = Principal(sub="u-1", tenant="acme", role="sales_rep")
ALLOWED = frozenset({"core", "deals"})
QUERY = Query(message="how do deal stages work", conversation_id="c-1")
CITATION = Citation(chunk_id="ch-1", doc_id="d", anchor="a", title="T", breadcrumb="Deals > T")


class Scripted:
    """A fake responder that yields a fixed script, optionally raising at the end."""

    versions = Versions(index_version="idx-7", prompt_version="answer@3", model_id="m-1")

    def __init__(
        self,
        script: Sequence[ContentEvent],
        raise_after: Exception | None = None,
        pin_error: Exception | None = None,
    ):
        self.script = script
        self.raise_after = raise_after
        self.pin_error = pin_error
        self.pinned: list[Versions] = []

    async def pin(self) -> Versions:
        if self.pin_error:
            raise self.pin_error
        return self.versions

    async def respond(
        self,
        query: Query,
        principal: Principal,
        allowed_modules: frozenset[str],
        versions: Versions,
    ) -> AsyncGenerator[ContentEvent, None]:
        self.pinned.append(versions)
        for event in self.script:
            yield event
        if self.raise_after:
            raise self.raise_after


async def run(responder: Scripted) -> tuple[list[WireEvent], list[TraceRecord]]:
    traces: list[TraceRecord] = []
    events = [
        e
        async for e in stream_events(
            responder, QUERY, PRINCIPAL, ALLOWED, trace_id="t-1", emit=traces.append
        )
    ]
    return events, traces


def types(events: list[WireEvent]) -> list[str]:
    return [e.type for e in events]


# --- happy paths --------------------------------------------------------------


async def test_answer_sequence_and_meta() -> None:
    usage = TokenUsage(input_tokens=5, output_tokens=2)
    events, traces = await run(
        Scripted(
            [
                Token(text="Open "),
                Token(text="Deals."),
                Citations(items=[CITATION]),
                Usage(usage=usage),
            ]
        )
    )
    assert types(events) == ["meta", "token", "token", "citations", "done"]
    assert events[0] == Meta(
        trace_id="t-1",
        conversation_id="c-1",
        index_version="idx-7",
        prompt_version="answer@3",
        model_id="m-1",
    )
    assert events[-1] == Done(usage=usage)
    assert [t.outcome for t in traces] == ["answer"]


async def test_answer_without_citations_is_allowed() -> None:
    events, _ = await run(Scripted([Token(text="ok")]))
    assert types(events) == ["meta", "token", "done"]


async def test_refusal_sequence() -> None:
    refusal = Refusal(kind="restricted", message="m", missing_modules=["campaigns"])
    events, traces = await run(Scripted([refusal]))
    assert types(events) == ["meta", "refusal", "done"]
    assert traces[0].outcome == "refusal:restricted"


# --- invariant violations become a single error terminal ----------------------


async def test_responder_exception_becomes_generic_error() -> None:
    events, traces = await run(
        Scripted([Token(text="Partial ")], raise_after=RuntimeError("db password hunter2"))
    )
    assert types(events) == ["meta", "token", "error"]
    err = events[-1]
    assert isinstance(err, ErrorEvent)
    assert "hunter2" not in err.message and "RuntimeError" not in err.message
    assert traces[0].outcome == "error"


async def test_token_then_refusal_is_rejected() -> None:
    events, _ = await run(Scripted([Token(text="Sure: "), Refusal(kind="not_found", message="m")]))
    assert types(events) == ["meta", "token", "error"]


async def test_refusal_then_token_is_rejected() -> None:
    events, _ = await run(Scripted([Refusal(kind="not_found", message="m"), Token(text="x")]))
    assert types(events) == ["meta", "refusal", "error"]


async def test_citations_before_any_token_is_rejected() -> None:
    events, _ = await run(Scripted([Citations(items=[CITATION])]))
    assert types(events) == ["meta", "error"]


async def test_token_after_citations_is_rejected() -> None:
    events, _ = await run(Scripted([Token(text="a"), Citations(items=[CITATION]), Token(text="b")]))
    assert types(events)[-1] == "error"


async def test_empty_response_is_rejected() -> None:
    events, _ = await run(Scripted([]))
    assert types(events) == ["meta", "error"]


# --- trace is written exactly once, including on disconnect ------------------


async def test_trace_contents() -> None:
    usage = TokenUsage(input_tokens=5, output_tokens=2)
    _, traces = await run(Scripted([Token(text="x"), Usage(usage=usage)]))
    (t,) = traces
    assert (t.trace_id, t.conversation_id) == ("t-1", "c-1")
    assert (t.sub, t.tenant, t.role) == ("u-1", "acme", "sales_rep")
    assert t.allowed_modules == ["core", "deals"]
    assert (t.index_version, t.prompt_version, t.model_id) == ("idx-7", "answer@3", "m-1")
    assert (t.input_tokens, t.output_tokens) == (5, 2)
    assert t.message_chars == len(QUERY.message)
    assert t.latency_ms >= 0


async def test_client_disconnect_still_traces_once() -> None:
    traces: list[TraceRecord] = []
    gen = stream_events(
        Scripted([Token(text="a"), Token(text="b"), Token(text="c")]),
        QUERY,
        PRINCIPAL,
        ALLOWED,
        trace_id="t-1",
        emit=traces.append,
    )
    await anext(gen)  # meta
    await anext(gen)  # first token
    await gen.aclose()
    assert [t.outcome for t in traces] == ["cancelled"]


async def test_respond_gets_exactly_the_versions_meta_and_the_trace_name() -> None:
    responder = Scripted([Token(text="hi"), Citations(items=[CITATION])])
    events, traces = await run(responder)
    assert responder.pinned == [Scripted.versions]
    assert isinstance(events[0], Meta) and events[0].index_version == "idx-7"
    assert traces[0].index_version == "idx-7"


async def test_a_pin_failure_is_still_a_well_formed_stream() -> None:
    events, traces = await run(Scripted([], pin_error=RuntimeError("no live index")))
    assert types(events) == ["meta", "error"]
    assert isinstance(events[0], Meta) and events[0].index_version == "unavailable"
    assert traces[0].outcome == "error"
