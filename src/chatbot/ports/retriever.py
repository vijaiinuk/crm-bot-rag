"""Retriever port (S2.2.1). Permission filtering happens inside the search, never after."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Candidate:
    chunk_id: str
    doc_id: str
    anchor: str
    breadcrumb: str
    content: str
    content_hash: str  # sha256 of the embedded text; keys the rerank cache
    modules: tuple[str, ...]
    index_version: int  # the version every search in the request used (rule 8)
    vec_rank: int | None  # 1-based rank in the vector list; None if not in it
    kw_rank: int | None  # 1-based rank in the keyword list; None if not in it
    score: float  # reciprocal rank fusion score
    rerank_score: float | None = None  # cross-encoder relevance, 0..1; set by the Reranker


class NoLiveIndex(Exception):
    """Nothing is live: a broken deployment, not an empty answer."""


class Retriever(Protocol):
    async def live_version(self) -> int:
        """The live index version. Read once per request; pass it to every search."""
        ...

    async def search(
        self, query: str, allowed_modules: frozenset[str], k: int, *, index_version: int
    ) -> list[Candidate]:
        """The top k chunks visible with `allowed_modules` (all of a chunk's modules)."""
        ...
