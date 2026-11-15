"""config/models.yaml: model roles -> pinned model IDs, providers and routing."""

import re
from pathlib import Path
from typing import Any

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

    @field_validator("model_id")
    @classmethod
    def _pinned(cls, v: str) -> str:
        if _UNPINNED.search(v):
            raise ValueError(f"{v!r} is not a pinned model version")
        return v


class ModelsConfig(_Strict):
    providers: dict[str, Provider]
    models: dict[str, ModelRole]

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
