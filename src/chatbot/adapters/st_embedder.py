"""bge-m3 via sentence-transformers, natively on MPS (CLAUDE.md: Docker has no GPU).

Dense vectors only, normalised so cosine distance (`<=>`) ranks correctly.
bge-m3 needs no query/passage prefix. The model is loaded lazily, so building
the object is cheap; a build whose chunks are all cached loads only the tokenizer.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from chatbot.models_config import EmbeddingConfig

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer
    from transformers import PreTrainedTokenizerBase


class SentenceTransformerEmbedder:
    def __init__(self, config: EmbeddingConfig, *, device: str | None = None) -> None:
        self._config = config
        self._device = device
        self._model: SentenceTransformer | None = None
        # Separate from the model: counting tokens (every build) must not load
        # 2.3 GB of weights when every chunk is already in the embedding cache.
        self._tokenizer: PreTrainedTokenizerBase | None = None

    @property
    def key(self) -> str:
        return self._config.key

    @property
    def dim(self) -> int:
        return self._config.dim

    def _load(self) -> "SentenceTransformer":
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            device = self._device or ("mps" if torch.backends.mps.is_available() else "cpu")
            model = SentenceTransformer(
                self._config.model_id, revision=self._config.revision, device=device
            )
            got = model.get_embedding_dimension()
            if got != self._config.dim:
                raise ValueError(f"{self.key} has dim {got}, config says {self._config.dim}")
            self._model = model
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._load().encode(
            list(texts),
            batch_size=self._config.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [[float(x) for x in v] for v in vectors]

    def count_tokens(self, text: str) -> int:
        if self._tokenizer is None:
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(
                self._config.model_id, revision=self._config.revision
            )
        return len(self._tokenizer(text, add_special_tokens=True)["input_ids"])
