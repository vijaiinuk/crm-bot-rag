"""S2.3.1: the eval run's wiring, with a fake retriever and reranker (no DB, no model)."""

from collections.abc import Sequence

import pytest

from chatbot.evals.golden import GoldenError, GoldenQuestion
from chatbot.evals.labels import OrphanLabels
from chatbot.evals.retrieval import render_markdown, run_retrieval_eval
from chatbot.ports.retriever import Candidate


def cand(chunk_id: str, score: float = 0.9) -> Candidate:
    doc, rest = chunk_id.split("#")
    return Candidate(
        chunk_id, doc, rest.split(":")[0], "B", "C", chunk_id, ("core",), 1, 1, None, score
    )


class FakeRetriever:
    def __init__(self, by_question: dict[str, list[str]]) -> None:
        self.by_question = by_question
        self.calls: list[tuple[str, frozenset[str]]] = []

    async def live_version(self) -> int:
        return 1

    async def search(
        self, query: str, allowed_modules: frozenset[str], k: int, *, index_version: int
    ) -> list[Candidate]:
        self.calls.append((query, allowed_modules))
        return [cand(c) for c in self.by_question.get(query, [])][:k]


class FakeReranker:
    key = "fake@1"

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    async def rerank(self, query: str, candidates: Sequence[Candidate], k: int) -> list[Candidate]:
        from dataclasses import replace

        scored = [replace(c, rerank_score=self.scores.get(c.chunk_id, 0.0)) for c in candidates]
        return sorted(scored, key=lambda c: -(c.rerank_score or 0.0))[:k]


PERSONAS = {
    "rep@acme": frozenset({"core", "deals"}),
    "mgr@acme": frozenset({"core", "deals", "campaigns"}),
}
GOLDEN = [
    GoldenQuestion.model_validate(
        {
            "id": "q-0001",
            "question": "move a deal",
            "category": "single",
            "expected": {
                "rep@acme": {"outcome": "answer", "required": ["deals-x#move"]},
                "mgr@acme": {"outcome": "answer", "required": ["deals-x#move"]},
            },
        }
    ),
    GoldenQuestion.model_validate(
        {
            "id": "q-0002",
            "question": "what is the weather",
            "category": "out_of_scope",
            "expected": {"rep@acme": {"outcome": "out_of_scope"}},
        }
    ),
]
LABELS = {
    "deals-x#other:0": frozenset({"deals-x#other"}),
    "deals-x#move:0": frozenset({"deals-x#move"}),
}


async def run(golden: list[GoldenQuestion] = GOLDEN, labels: dict[str, frozenset[str]] = LABELS):  # type: ignore[no-untyped-def]
    retriever = FakeRetriever(
        {
            "move a deal": ["deals-x#other:0", "deals-x#move:0"],
            "what is the weather": ["deals-x#other:0"],
        }
    )
    reranker = FakeReranker({"deals-x#move:0": 0.95, "deals-x#other:0": 0.05})
    result = await run_retrieval_eval(
        golden, PERSONAS, retriever, reranker, labels, index_version=1, threshold=0.3, ks=(1, 2)
    )
    return result, retriever


async def test_both_stages_are_scored_and_only_answer_pairs_count() -> None:
    result, _ = await run()
    assert result.summaries["hybrid"]["single"].complete == {1: 0.0, 2: 1.0}  # move was 2nd
    assert result.summaries["rerank"]["single"].complete == {1: 1.0, 2: 1.0}  # rerank fixed it
    assert result.summaries["rerank"]["overall"].n == 2, "two answer pairs; out_of_scope not scored"


async def test_every_pair_is_searched_with_its_own_personas_modules() -> None:
    _, retriever = await run()
    assert retriever.calls == [
        ("move a deal", PERSONAS["rep@acme"]),
        ("move a deal", PERSONAS["mgr@acme"]),
        ("what is the weather", PERSONAS["rep@acme"]),
    ]


async def test_the_threshold_check_covers_every_pair() -> None:
    result, _ = await run()
    assert (result.gate["answer"].n, result.gate["answer"].above) == (2, 2)
    assert (result.gate["nothing"].n, result.gate["nothing"].above) == (1, 0)
    assert len(result.pairs) == 3


async def test_an_orphan_label_aborts_before_any_search() -> None:
    with pytest.raises(OrphanLabels, match="deals-x#move"):
        await run(labels={"deals-x#other:0": frozenset({"deals-x#other"})})


async def test_an_unknown_persona_aborts() -> None:
    bad = GOLDEN[0].model_copy(
        update={"expected": {"ghost@nowhere": GOLDEN[0].expected["rep@acme"]}}
    )
    with pytest.raises(GoldenError, match="ghost@nowhere"):
        await run(golden=[bad])


async def test_the_report_has_both_stages_and_the_threshold_table() -> None:
    result, _ = await run()
    md = render_markdown(result, {"git": "abc"})
    assert "## Hybrid + rerank" in md and "## Hybrid only" in md and "## Threshold 0.3" in md
    assert "| **overall** | 2 |" in md
