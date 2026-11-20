"""S3.1.3b: done when answers stream with verified citations, and low-confidence and
restricted cases get the right response. Retriever, reranker, matcher scores and the
LLM are all fakes; the pipeline logic is real."""

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import httpx

from chatbot.adapters.local_catalogue import load_catalogue
from chatbot.adapters.rag_responder import RagResponder
from chatbot.events import Citations, ContentEvent, Refusal, Token, Usage
from chatbot.generation.module_match import ModuleMatcher
from chatbot.generation.prompt import load_prompt
from chatbot.ports.entitlements import Principal
from chatbot.ports.llm import Completion, Message
from chatbot.ports.llm import Usage as LLMUsage
from chatbot.ports.responder import Query, Versions
from chatbot.ports.retriever import Candidate

ROOT = Path(__file__).parents[2]
CATALOGUE = load_catalogue(ROOT / "data" / "module_catalogue.yaml")
PROMPT = load_prompt(ROOT / "prompts" / "answer_v1.md")
REP = frozenset({"core", "contacts", "deals"})  # no campaigns, no products
VERSIONS = Versions("7", PROMPT.version, "fake-model")


def cand(chunk_id: str, modules: tuple[str, ...], score: float) -> Candidate:
    doc, rest = chunk_id.split("#")
    return Candidate(
        chunk_id,
        doc,
        rest.split(":")[0],
        f"Title {doc} > {rest.split(':')[0]}",
        f"content of {chunk_id}",
        f"h-{chunk_id}",
        modules,
        7,
        1,
        None,
        0.01,
        rerank_score=score,
    )


class FakeRetriever:
    def __init__(self, chunks: Sequence[Candidate]) -> None:
        self.chunks = chunks
        self.calls: list[tuple[frozenset[str], int]] = []

    async def live_version(self) -> int:
        return 7

    async def search(
        self, query: str, allowed_modules: frozenset[str], k: int, *, index_version: int
    ) -> list[Candidate]:
        self.calls.append((allowed_modules, index_version))
        return [c for c in self.chunks if set(c.modules) <= allowed_modules][:k]


class FakeReranker:
    key = "fake@1"

    async def rerank(self, query: str, candidates: Sequence[Candidate], k: int) -> list[Candidate]:
        return sorted(candidates, key=lambda c: -(c.rerank_score or 0))[:k]


class FakeLLM:
    def __init__(self, deltas: Sequence[str]) -> None:
        self.deltas = deltas
        self.messages: list[Sequence[Message]] = []

    async def complete(self, messages: Sequence[Message], *, role: str) -> Completion:
        raise NotImplementedError

    async def stream(
        self, messages: Sequence[Message], *, role: str
    ) -> AsyncIterator[str | Completion]:
        self.messages.append(messages)
        for d in self.deltas:
            yield d
        yield Completion("".join(self.deltas), "fake-model", "fake", LLMUsage(120, 30), 5)


def matcher(scores: dict[str, float]) -> ModuleMatcher:
    """Similarity per module; modules not listed (incl. the rep's own) score 0."""

    async def score(question: str, texts: Sequence[str]) -> list[float]:
        names = {m.profile: n for n, m in CATALOGUE.modules.items()}
        return [scores.get(names[t], 0.0) for t in texts]

    return ModuleMatcher(CATALOGUE, score, floor=0.45)


def responder(
    chunks: Sequence[Candidate],
    deltas: Sequence[str] = (),
    module_scores: dict[str, float] | None = None,
) -> tuple[RagResponder, FakeRetriever, FakeLLM]:
    retriever, llm = FakeRetriever(chunks), FakeLLM(deltas)
    r = RagResponder(
        retriever=retriever,
        reranker=FakeReranker(),
        matcher=matcher(module_scores or {}),
        llm=llm,
        model_id="fake-model",
        prompt=PROMPT,
        catalogue=CATALOGUE,
        threshold=0.3,
    )
    return r, retriever, llm


async def events(r: RagResponder, question: str = "how do I move a deal") -> list[ContentEvent]:
    return [
        e
        async for e in r.respond(
            Query(question, "c"), Principal("u", "acme", "sales_rep"), REP, VERSIONS
        )
    ]


def text(evs: list[ContentEvent]) -> str:
    return "".join(e.text for e in evs if isinstance(e, Token))


DEALS = [
    cand("deals-board#drag:0", ("deals",), 0.97),
    cand("deals-board#filter:0", ("deals",), 0.6),
]
SECRET = cand("campaigns-x#steps:0", ("campaigns",), 0.99)


# --- answers --------------------------------------------------------------------------------


async def test_an_answer_streams_without_markers_and_cites_the_right_chunks() -> None:
    r, retriever, _ = responder(DEALS, ["1. Drag the ", "card [1].\n2. Check ", "filters [2]."])
    evs = await events(r)
    assert text(evs) == "1. Drag the card.\n2. Check filters."
    cites = next(e for e in evs if isinstance(e, Citations)).items
    assert [c.chunk_id for c in cites] == ["deals-board#drag:0", "deals-board#filter:0"]
    assert cites[0].title == "Title deals-board" and cites[0].anchor == "drag"
    assert isinstance(evs[-1], Usage) and evs[-1].usage.input_tokens == 120
    assert retriever.calls == [(REP, 7)], "searched with the pinned version and own modules"


async def test_a_citation_number_outside_the_context_is_dropped() -> None:
    r, _, _ = responder(DEALS, ["Drag it [1]. Also [9]."])
    evs = await events(r)
    assert [c.chunk_id for c in next(e for e in evs if isinstance(e, Citations)).items] == [
        "deals-board#drag:0"
    ]
    assert r.last_invalid_citations == 1


async def test_restricted_content_never_reaches_the_prompt() -> None:
    """Rule 3: the retriever filters; the prompt holds only allowed excerpts."""
    r, _, llm = responder([*DEALS, SECRET], ["Drag it [1]."])
    await events(r)
    prompt = "\n".join(m.content for m in llm.messages[0])
    assert "content of deals-board#drag:0" in prompt
    assert "campaigns-x" not in prompt


async def test_the_versions_pinned_are_the_live_index_prompt_and_model() -> None:
    r, _, _ = responder(DEALS)
    v = await r.pin()
    assert (v.index_version, v.prompt_version, v.model_id) == ("7", PROMPT.version, "fake-model")


# --- below threshold: no LLM call -----------------------------------------------------------


async def test_low_confidence_with_no_restricted_match_is_not_found() -> None:
    r, _, llm = responder([cand("d#x:0", ("deals",), 0.05)])
    evs = await events(r, "what is the weather tomorrow")
    assert [type(e) for e in evs] == [Refusal]
    assert isinstance(evs[0], Refusal) and evs[0].kind == "not_found"
    assert llm.messages == [], "below threshold: the LLM is never called"


async def test_low_confidence_matching_a_module_the_user_lacks_is_the_restricted_template() -> None:
    r, _, llm = responder([cand("d#x:0", ("deals",), 0.05)], module_scores={"campaigns": 0.9})
    [refusal] = await events(r, "how do I send a newsletter to an audience")
    assert isinstance(refusal, Refusal) and refusal.kind == "restricted"
    assert refusal.missing_modules == ["campaigns"]
    assert "Campaigns" in refusal.message and CATALOGUE.restricted_contact in refusal.message
    assert llm.messages == []


async def test_no_candidates_at_all_is_not_found() -> None:
    r, _, _ = responder([])
    [refusal] = await events(r)
    assert isinstance(refusal, Refusal) and refusal.kind == "not_found"


# --- the model says the excerpts don't answer -----------------------------------------------


async def test_the_not_found_sentinel_becomes_a_refusal_with_no_tokens() -> None:
    r, _, llm = responder(DEALS, ["[[NOT", "_FOUND]]"])
    evs = await events(r)
    assert not any(isinstance(e, Token) for e in evs)
    assert isinstance(evs[0], Refusal) and evs[0].kind == "not_found"
    assert llm.messages, "the LLM was asked; its usage is still reported"
    assert isinstance(evs[-1], Usage)


async def test_the_sentinel_with_a_restricted_match_is_the_restricted_template() -> None:
    r, _, _ = responder(DEALS, ["[[NOT_FOUND]]"], module_scores={"products": 0.8})
    evs = await events(r)
    assert isinstance(evs[0], Refusal) and evs[0].missing_modules == ["products"]


# --- partial access -------------------------------------------------------------------------


async def test_partial_access_answers_from_allowed_docs_and_adds_the_templated_note() -> None:
    r, _, llm = responder(
        DEALS, ["Create the quote from the deal [1]."], module_scores={"products": 0.8}
    )
    evs = await events(r, "how do I add products from a price book to a quote from a deal")
    body = text(evs)
    assert body.startswith("Create the quote from the deal.")
    assert body.endswith(
        "Parts of this may involve Products, which isn't included in your current access, "
        f"so this answer covers only what you can use. {CATALOGUE.restricted_contact}"
    )
    assert "Products" not in "\n".join(m.content for m in llm.messages[0]), "the note is ours"
    assert isinstance(next(e for e in evs if isinstance(e, Citations)), Citations)


# --- end to end through /chat ---------------------------------------------------------------


async def test_the_rag_responder_streams_a_well_formed_answer_through_chat(
    settings: Any, jwks_source: Any, mint: Any
) -> None:
    from chatbot.adapters.local_entitlements import LocalEntitlementProvider
    from chatbot.api.app import create_app
    from tests.conftest import PERSONAS, parse_sse

    r, _, _ = responder(DEALS, ["Drag the card [1]."])
    app = create_app(
        settings,
        jwks_source=jwks_source,
        entitlements=LocalEntitlementProvider(PERSONAS),
        responder=r,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post(
            "/chat",
            json={"message": "how do I move a deal"},
            headers={"Authorization": f"Bearer {mint()}"},
        )
    evs = parse_sse(resp.text)
    names = [n for n, _ in evs]
    assert names[0] == "meta" and names[-2:] == ["citations", "done"]
    assert evs[0][1]["index_version"] == "7" and evs[0][1]["prompt_version"] == PROMPT.version
    assert "".join(d["text"] for n, d in evs if n == "token") == "Drag the card."
    assert evs[-2][1]["items"][0]["chunk_id"] == "deals-board#drag:0"
