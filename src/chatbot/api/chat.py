import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from chatbot.api.auth import CurrentUserDep
from chatbot.events import to_sse
from chatbot.ports.responder import Query, Responder
from chatbot.streaming import stream_events

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
    query = Query(
        message=body.message,
        conversation_id=str(body.conversation_id or uuid.uuid4()),
    )
    events = stream_events(
        responder, query, user.principal, user.allowed_modules, trace_id=uuid.uuid4().hex
    )

    async def sse() -> AsyncIterator[bytes]:
        async for event in events:
            yield to_sse(event)

    return StreamingResponse(sse(), media_type="text/event-stream", headers=SSE_HEADERS)
