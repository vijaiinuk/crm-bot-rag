from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0


@dataclass(frozen=True, slots=True)
class Completion:
    """One LLM call's result, with what's needed for traces and cost rows (rule 8)."""

    text: str
    model_id: str  # the pinned ID from config/models.yaml
    provider: str  # the backend that actually served the call
    usage: Usage
    latency_ms: int


class LLMError(Exception):
    """The call failed, returned nothing, or was served by an unexpected provider."""


class LLMClient(Protocol):
    """Calls a model by role (`docgen`, later `rewrite`, `generate`, `judge`).

    Roles map to pinned model IDs in config/models.yaml, so callers never name
    a model. Structured output (`schema`) arrives with S3.1.3.
    """

    async def complete(self, messages: Sequence[Message], *, role: str) -> Completion: ...


class StreamingLLMClient(LLMClient, Protocol):
    """An LLMClient that can also stream (answer generation, S3.1.3b)."""

    def stream(self, messages: Sequence[Message], *, role: str) -> AsyncIterator[str | Completion]:
        """Text deltas as they arrive, then exactly one Completion (full text, usage)."""
        ...
