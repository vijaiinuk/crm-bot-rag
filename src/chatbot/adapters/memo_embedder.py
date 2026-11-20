"""Embed each distinct text once per process: evals and the gate search the same texts
under many entitlement sets."""

from collections.abc import Sequence

from chatbot.ports.embedder import Embedder


class MemoEmbedder:
    def __init__(self, inner: Embedder) -> None:
        self._inner = inner
        self._memo: dict[str, list[float]] = {}

    @property
    def key(self) -> str:
        return self._inner.key

    @property
    def dim(self) -> int:
        return self._inner.dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        missing = [t for t in dict.fromkeys(texts) if t not in self._memo]
        if missing:
            self._memo.update(zip(missing, self._inner.embed(missing), strict=True))
        return [self._memo[t] for t in texts]

    def count_tokens(self, text: str) -> int:
        return self._inner.count_tokens(text)
