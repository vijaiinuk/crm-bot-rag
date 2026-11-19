"""Cross-encoder reranking (S2.2.2).

A cross-encoder reads the question and a chunk together, so it judges relevance far
better than comparing two separately made vectors, but it costs one model pass per
candidate. So it only reorders hybrid search's top candidates.

Scores are sigmoid(logit), computed here rather than by the library's default
activation, so a threshold always means the same thing.
"""

import asyncio
import dataclasses
import math
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from chatbot.models_config import RerankerConfig
from chatbot.ports.retriever import Candidate

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

ScorePairs = Callable[[list[tuple[str, str]]], list[float]]  # (query, passage) -> logits


def passage(c: Candidate) -> str:
    """What the cross-encoder reads: the same breadcrumb + content that was embedded."""
    return f"{c.breadcrumb}\n\n{c.content}"


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x)) if x >= 0 else math.exp(x) / (1.0 + math.exp(x))


class CrossEncoderReranker:
    def __init__(
        self,
        config: RerankerConfig,
        *,
        device: str | None = None,
        score_pairs: ScorePairs | None = None,  # tests inject a fake; default loads the model
    ) -> None:
        self._config = config
        self._device = device
        self._score_pairs = score_pairs or self._model_logits
        self._model: CrossEncoder | None = None

    @property
    def key(self) -> str:
        return self._config.key

    async def rerank(self, query: str, candidates: Sequence[Candidate], k: int) -> list[Candidate]:
        if k < 1:
            raise ValueError(f"k must be at least 1, got {k}")
        if not candidates:
            return []
        pairs = [(query, passage(c)) for c in candidates]
        logits = await asyncio.to_thread(self._score_pairs, pairs)
        if len(logits) != len(candidates):
            raise ValueError(f"got {len(logits)} scores for {len(candidates)} candidates")
        scored = [
            dataclasses.replace(c, rerank_score=sigmoid(float(x)))
            for c, x in zip(candidates, logits, strict=True)
        ]
        # Stable sort: equal scores keep the fused (input) order.
        scored.sort(key=lambda c: -(c.rerank_score or 0.0))
        return scored[:k]

    def _load(self) -> "CrossEncoder":
        if self._model is None:
            import torch
            from sentence_transformers import CrossEncoder

            device = self._device or ("mps" if torch.backends.mps.is_available() else "cpu")
            # float16 halves memory on MPS (scores within 0.001 of float32, same top
            # candidate on 30/30 golden questions); CPU float16 is slow, so float32 there.
            dtype = torch.float16 if device == "mps" and self._config.dtype == "float16" else None
            self._model = CrossEncoder(
                self._config.model_id,
                revision=self._config.revision,
                device=device,
                max_length=self._config.max_length,
                model_kwargs={"torch_dtype": dtype} if dtype is not None else None,
            )
        return self._model

    def _model_logits(self, pairs: list[tuple[str, str]]) -> list[float]:
        import torch

        raw = self._load().predict(
            pairs,
            batch_size=self._config.batch_size,
            activation_fn=torch.nn.Identity(),  # raw logits; we apply the sigmoid
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [float(x) for x in raw]
