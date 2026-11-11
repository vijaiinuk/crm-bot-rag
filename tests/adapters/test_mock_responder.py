from pathlib import Path

import pytest
import yaml

from chatbot.adapters.local_catalogue import load_catalogue
from chatbot.adapters.mock_responder import MOCK_DOCS, MockResponder
from chatbot.events import Citations, ContentEvent, Refusal, Token
from chatbot.ports.entitlements import Principal
from chatbot.ports.responder import Query
from chatbot.refusals import not_found_message, restricted_message

DATA = Path(__file__).parents[2] / "data"
CATALOGUE = load_catalogue(DATA / "module_catalogue.yaml")
PERSONAS: dict[str, list[str]] = yaml.safe_load((DATA / "personas.yaml").read_text())["personas"]

MANAGER = frozenset(PERSONAS["sales_manager@acme"])
REP = frozenset(PERSONAS["sales_rep@globex"])

SCENARIOS = [
    "how do I move a deal to the next stage",
    "set up a triggered campaign email",
    "build a dashboard report",
    "import contacts from a csv",
    "email contacts when a deal changes stage",
    "pipeline dashboard for my contacts",
    "what is the meaning of life",
    "",
]


async def collect(message: str, allowed: frozenset[str]) -> list[ContentEvent]:
    responder = MockResponder(CATALOGUE)
    principal = Principal(sub="u", tenant="t", role="r")
    return [e async for e in responder.respond(Query(message, "c"), principal, allowed)]


def text_of(events: list[ContentEvent]) -> str:
    return "".join(e.text for e in events if isinstance(e, Token))


async def test_allowed_question_streams_answer_with_citation() -> None:
    events = await collect("how do I move a deal to the next stage", MANAGER)
    assert sum(isinstance(e, Token) for e in events) > 3, "should stream in pieces"
    (cites,) = [e for e in events if isinstance(e, Citations)]
    assert [c.doc_id for c in cites.items] == ["deals-stage-automation"]
    assert "1." in text_of(events), "answer includes numbered steps"


async def test_restricted_question_is_templated_refusal_with_no_content() -> None:
    events = await collect("set up a triggered campaign email", REP)
    assert not any(isinstance(e, Token | Citations) for e in events)
    (refusal,) = [e for e in events if isinstance(e, Refusal)]
    assert refusal.kind == "restricted"
    assert refusal.missing_modules == ["campaigns"]
    assert refusal.message == restricted_message(["campaigns"], CATALOGUE)


async def test_cross_module_question_needs_every_module() -> None:
    events = await collect("email contacts when a deal changes stage", REP)
    (refusal,) = [e for e in events if isinstance(e, Refusal)]
    assert refusal.missing_modules == ["campaigns"], (
        "deals and contacts are allowed; only report what's missing"
    )
    assert not any(isinstance(e, Token) for e in events)


async def test_cross_module_answer_cites_each_module() -> None:
    events = await collect("email contacts when a deal changes stage", MANAGER)
    (cites,) = [e for e in events if isinstance(e, Citations)]
    assert {c.doc_id for c in cites.items} == {
        "deals-stage-automation",
        "campaigns-triggered-emails",
        "contacts-import",
    }


async def test_unmatched_question_is_not_found() -> None:
    events = await collect("what is the meaning of life", MANAGER)
    assert events == [Refusal(kind="not_found", message=not_found_message())]


async def test_keywords_match_whole_word_prefixes_only() -> None:
    """'ideal' must not match 'deal'."""
    events = await collect("what is the ideal approach", MANAGER)
    assert [e.kind for e in events if isinstance(e, Refusal)] == ["not_found"]


async def test_simulated_error_raises_mid_stream() -> None:
    responder = MockResponder(CATALOGUE)
    gen = responder.respond(Query("simulate:error", "c"), Principal("u", "t", "r"), MANAGER)
    assert isinstance(await anext(gen), Token)
    with pytest.raises(RuntimeError):
        async for _ in gen:
            pass


@pytest.mark.parametrize("persona", sorted(PERSONAS))
@pytest.mark.parametrize("message", SCENARIOS)
async def test_permission_sweep_no_citation_outside_allowed(persona: str, message: str) -> None:
    """Zero tolerance, in miniature: nothing cited or streamed from a disallowed module."""
    allowed = frozenset(PERSONAS[persona])
    module_of = {d.doc_id: d.module for d in MOCK_DOCS}
    events = await collect(message, allowed)
    for e in events:
        if isinstance(e, Citations):
            assert {module_of[c.doc_id] for c in e.items} <= allowed
    if any(isinstance(e, Refusal) for e in events):
        assert not any(isinstance(e, Token | Citations) for e in events)
    restricted_bodies = [d.body for d in MOCK_DOCS if d.module not in allowed]
    streamed = text_of(events)
    assert not any(body in streamed for body in restricted_bodies)
