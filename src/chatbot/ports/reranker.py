"""Reranker port (S2.2.2). Local: bge-reranker-v2-m3 on MPS. Production compute is an
open question (architecture §10); callers never change."""

from collections.abc import Sequence
from typing import Protocol

from chatbot.ports.retriever import Candidate


class Reranker(Protocol):
    @property
    def key(self) -> str:
        """Model id and exact revision, for traces."""
        ...

    async def rerank(self, query: str, candidates: Sequence[Candidate], k: int) -> list[Candidate]:
        """The best k of `candidates`, each with `rerank_score` set, best first.

        Only reorders and cuts: never adds a candidate, so it cannot widen access.
        """
        ...
