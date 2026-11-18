"""Embedder port (S2.1.3). Local: bge-m3 on MPS. Production: the same model on
whatever compute the reranker ADR settles on; callers never change."""

from collections.abc import Sequence
from typing import Protocol


class Embedder(Protocol):
    @property
    def key(self) -> str:
        """Model id and exact revision; the embedding cache and index recipe record it."""
        ...

    @property
    def dim(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One unit-length vector per text, in order."""
        ...

    def count_tokens(self, text: str) -> int:
        """Tokens as this model sees them; the chunker's size limit uses it."""
        ...
