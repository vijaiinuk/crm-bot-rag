"""Which modules the user lacks does a question concern? (S3.1.3b)

Scored against each module's PUBLIC catalogue profile (name, description, UI labels,
entity names), never against chunks: no retrieval outside the allowed modules happens
at all (rule 2), and only catalogue text is ever shown (rule 7).

Rule (calibrated on the golden set, S3.1.3b design): a module the user lacks matches if
it is at least as similar to the question as every module they have, and above a
floor. The relative test is what keeps answerable questions from getting a spurious
"this may involve..." note (0.5% of pairs, vs 14% for an absolute cut-off).
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence

import numpy as np

from chatbot.ports.catalogue import ModuleCatalogue
from chatbot.ports.embedder import Embedder

ScoreTexts = Callable[[str, Sequence[str]], Awaitable[list[float]]]


def embedding_similarity(embedder: Embedder) -> ScoreTexts:
    """Cosine similarity (unit vectors) of a question to texts; text vectors cached."""
    cache: dict[str, np.ndarray] = {}

    async def score(question: str, texts: Sequence[str]) -> list[float]:
        missing = [t for t in dict.fromkeys(texts) if t not in cache]
        vectors = await asyncio.to_thread(embedder.embed, [question, *missing])
        cache.update(zip(missing, (np.asarray(v) for v in vectors[1:]), strict=True))
        q = np.asarray(vectors[0])
        return [float(q @ cache[t]) for t in texts]

    return score


class ModuleMatcher:
    def __init__(self, catalogue: ModuleCatalogue, similarity: ScoreTexts, floor: float) -> None:
        self._catalogue = catalogue
        self._similarity = similarity
        self._floor = floor

    async def scores(self, question: str) -> dict[str, float]:
        """Similarity of the question to every module's public profile."""
        names = list(self._catalogue.modules)
        profiles = [self._catalogue.modules[m].profile for m in names]
        return dict(zip(names, await self._similarity(question, profiles), strict=True))

    async def missing_modules(self, question: str, allowed: frozenset[str]) -> list[str]:
        """Modules the user lacks that the question is about, best match first."""
        if set(self._catalogue.modules) <= allowed:
            return []
        scored = await self.scores(question)
        best_held = max((v for m, v in scored.items() if m in allowed), default=0.0)
        hits = [
            m for m, v in scored.items() if m not in allowed and v >= self._floor and v >= best_held
        ]
        return sorted(hits, key=lambda m: -scored[m])
