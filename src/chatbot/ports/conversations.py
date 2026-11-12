from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from chatbot.ports.entitlements import Principal
from chatbot.tracing.log import TraceRecord


@dataclass(frozen=True, slots=True)
class ChatTurn:
    """One question and its answer, already redacted, plus the request's trace."""

    trace: TraceRecord
    question: str
    answer: str
    at: datetime


class ConversationStore(Protocol):
    """Server-owned conversations (architecture §3 step 0)."""

    async def open_conversation(
        self, conversation_id: str | None, principal: Principal, at: datetime
    ) -> str | None:
        """Create a conversation (id None) or return the id if `principal` owns it.

        Returns None for an unknown id or one owned by someone else: the caller
        answers 404 either way, so the response doesn't reveal which.
        """
        ...

    def record_turn(self, turn: ChatTurn) -> None:
        """Store messages and cost rows. Synchronous: it runs in the stream's
        `finally`, including on disconnect; a database adapter should enqueue."""
        ...
