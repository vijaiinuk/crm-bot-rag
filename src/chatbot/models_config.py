"""config/models.yaml: model roles -> pinned model IDs, providers and routing."""

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

# "latest", "-preview" style moving aliases are not pinned (ADR-0002).
_UNPINNED = re.compile(r"(latest|:free$|^openrouter/auto$)")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Provider(_Strict):
    api_base: str


class Route(_Strict):
    """OpenRouter provider routing. Pinned to one backend, fallbacks off."""

    order: list[str] = Field(min_length=1, max_length=1)
    allow_fallbacks: bool

    @field_validator("allow_fallbacks")
    @classmethod
    def _no_fallbacks(cls, v: bool) -> bool:
        if v:
            raise ValueError("fallbacks must be off, so one model ID has one backend")
        return v


class ModelParams(_Strict):
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(gt=0)


class ModelRole(_Strict):
    provider: str
    model_id: str
    route: Route
    params: ModelParams
    # Client-side pacing: at most this many requests a minute (provider limits).
    rpm: int | None = Field(default=None, ge=1)

    @field_validator("model_id")
    @classmethod
    def _pinned(cls, v: str) -> str:
        if _UNPINNED.search(v):
            raise ValueError(f"{v!r} is not a pinned model version")
        return v


class EmbeddingConfig(_Strict):
    """The local embedding model (S2.1.3), pinned to a Hugging Face commit."""

    model_id: str
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")  # a commit sha, never a branch
    dim: int = Field(gt=0)
    batch_size: int = Field(default=16, gt=0)

    @property
    def key(self) -> str:
        """What the embedding cache and index recipe record: model and exact revision."""
        return f"{self.model_id}@{self.revision[:12]}"


class RerankerConfig(_Strict):
    """The local cross-encoder (S2.2.2). The threshold lives here because it only means
    something on this model's score scale: change the model, recalibrate the threshold."""

    model_id: str
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    max_length: int = Field(gt=0)
    batch_size: int = Field(default=16, gt=0)
    # Precision on MPS. CPU always runs float32 (float16 is slow there).
    dtype: Literal["float32", "float16"] = "float32"
    # Sigmoid of the model's logit. Below it on the best candidate: no LLM call.
    threshold: float = Field(ge=0, le=1)

    @property
    def key(self) -> str:
        return f"{self.model_id}@{self.revision[:12]}"


class ModelsConfig(_Strict):
    providers: dict[str, Provider]
    models: dict[str, ModelRole]
    embeddings: EmbeddingConfig | None = None
    reranker: RerankerConfig | None = None

    @model_validator(mode="after")
    def _known_providers(self) -> "ModelsConfig":
        for role, m in self.models.items():
            if m.provider not in self.providers:
                raise ValueError(f"models.{role}: unknown provider {m.provider!r}")
        return self


class ModelsConfigError(ValueError):
    pass


def load_models_config(path: Path) -> ModelsConfig:
    try:
        raw: Any = yaml.safe_load(path.read_text())
        return ModelsConfig.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as e:
        raise ModelsConfigError(f"{path}: {e}") from e
