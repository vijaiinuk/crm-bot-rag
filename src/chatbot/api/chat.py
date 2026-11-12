import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from chatbot.api.auth import CurrentUserDep
from chatbot.events import to_sse
from chatbot.ports.conversations import ChatTurn, ConversationStore
from chatbot.ports.redactor import Redactor
from chatbot.ports.responder import Query, Responder
from chatbot.streaming import stream_events
from chatbot.tracing.log import TraceRecord

router = APIRouter()

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


class ChatRequest(BaseModel):
    # extra="forbid": a body carrying modules/tenant/role is rejected, not ignored (rule 1).
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None


@router.post("/chat")
async def chat(body: ChatRequest, user: CurrentUserDep, request: Request) -> StreamingResponse:
    responder: Responder = request.app.state.responder
    store: ConversationStore = request.app.state.conversations
    redactor: Redactor = request.app.state.redactor

    # Conversations are server-owned: an unknown id, or someone else's, is a 404
    # before any stream starts (and the two cases are indistinguishable).
    requested = str(body.conversation_id) if body.conversation_id else None
    conversation_id = await store.open_conversation(requested, user.principal, datetime.now(UTC))
    if conversation_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")

    question = redactor.redact(body.message)

    def record(trace: TraceRecord, answer: str) -> None:
        store.record_turn(
            ChatTurn(
                trace=trace, question=question, answer=redactor.redact(answer), at=datetime.now(UTC)
            )
        )

    events = stream_events(
        responder,
        Query(message=body.message, conversation_id=conversation_id),
        user.principal,
        user.allowed_modules,
        trace_id=uuid.uuid4().hex,
        on_complete=record,
    )

    async def sse() -> AsyncIterator[bytes]:
        async for event in events:
            yield to_sse(event)

    return StreamingResponse(sse(), media_type="text/event-stream", headers=SSE_HEADERS)
