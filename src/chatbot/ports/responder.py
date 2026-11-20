from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol

from chatbot.events import ContentEvent
from chatbot.ports.entitlements import Principal


@dataclass(frozen=True, slots=True)
class Versions:
    """What produced an answer; carried on `meta` and in every trace (rule 8)."""

    index_version: str
    prompt_version: str
    model_id: str


@dataclass(frozen=True, slots=True)
class Query:
    message: str
    conversation_id: str


class Responder(Protocol):
    """Turns a question into content events. The mock now; the RAG pipeline later.

    Implementations must only ever use content from `allowed_modules`. Event
    ordering is enforced by chatbot.streaming, not trusted to the responder.
    """

    async def pin(self) -> Versions:
        """Resolve what this request will use (e.g. the live index version), once, so the
        `meta` event, the trace and the search all name the same version (rule 8)."""
        ...

    def respond(
        self,
        query: Query,
        principal: Principal,
        allowed_modules: frozenset[str],
        versions: Versions,
    ) -> AsyncGenerator[ContentEvent, None]: ...
