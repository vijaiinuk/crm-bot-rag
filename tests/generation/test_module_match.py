"""S3.1.3b: matching a question to modules the user lacks, on public profiles only."""

from collections.abc import Sequence
from pathlib import Path

import numpy as np

from chatbot.adapters.local_catalogue import load_catalogue
from chatbot.generation.module_match import ModuleMatcher, embedding_similarity

ROOT = Path(__file__).parents[2]
CATALOGUE = load_catalogue(ROOT / "data" / "module_catalogue.yaml")
NAMES = {m.profile: name for name, m in CATALOGUE.modules.items()}


class Similarity:
    """Fake similarity per module; records what text it was asked to score."""

    def __init__(self, by_module: dict[str, float]) -> None:
        self.by_module = by_module
        self.seen: list[str] = []

    async def __call__(self, question: str, texts: Sequence[str]) -> list[float]:
        self.seen += texts
        return [self.by_module.get(NAMES[t], 0.0) for t in texts]


REP = frozenset({"core", "contacts", "deals"})


async def test_a_lacking_module_matches_when_it_beats_every_held_module() -> None:
    sim = Similarity({"campaigns": 0.6, "deals": 0.5, "contacts": 0.3})
    assert await ModuleMatcher(CATALOGUE, sim, 0.45).missing_modules("q", REP) == ["campaigns"]
    assert set(sim.seen) == {m.profile for m in CATALOGUE.modules.values()}, "profiles only"


async def test_no_match_when_a_held_module_fits_the_question_better() -> None:
    """The relative rule: a deals question from someone with deals gets no note."""
    sim = Similarity({"campaigns": 0.55, "deals": 0.7})
    assert await ModuleMatcher(CATALOGUE, sim, 0.45).missing_modules("q", REP) == []


async def test_no_match_below_the_floor_even_if_it_beats_held_modules() -> None:
    sim = Similarity({"campaigns": 0.40, "deals": 0.2})  # e.g. "what's the weather"
    assert await ModuleMatcher(CATALOGUE, sim, 0.45).missing_modules("q", REP) == []


async def test_several_matches_come_best_first() -> None:
    sim = Similarity({"reports": 0.6, "campaigns": 0.8, "deals": 0.5})
    assert await ModuleMatcher(CATALOGUE, sim, 0.45).missing_modules("q", REP) == [
        "campaigns",
        "reports",
    ]


async def test_a_user_with_every_module_needs_no_scoring() -> None:
    sim = Similarity({})
    matcher = ModuleMatcher(CATALOGUE, sim, 0.45)
    assert await matcher.missing_modules("q", frozenset(CATALOGUE.modules)) == []
    assert sim.seen == []


async def test_embedding_similarity_is_cosine_and_caches_text_vectors() -> None:
    class Embed:
        key, dim = "e", 2

        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            self.calls.append(list(texts))
            return [[1.0, 0.0] if t in ("q", "a") else [0.0, 1.0] for t in texts]

        def count_tokens(self, text: str) -> int:
            return 1

    e = Embed()
    score = embedding_similarity(e)
    assert await score("q", ["a", "b"]) == [1.0, 0.0]
    await score("q2", ["a", "b"])
    assert e.calls == [["q", "a", "b"], ["q2"]], "profiles embedded once"
    assert np.isclose((await score("q", ["b"]))[0], 0.0)
