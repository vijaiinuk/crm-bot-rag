"""Chat stream events: the wire contract between the API and any client.

Wire format (SSE): `event: <type>` + `data: <json without type>`.
Allowed sequences, enforced in chatbot.streaming:

    meta → token+ → citations? → done
    meta → refusal → done
    meta → ... → error
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TokenUsage(_Model):
    input_tokens: int = 0
    output_tokens: int = 0


class Citation(_Model):
    chunk_id: str
    doc_id: str
    anchor: str
    title: str
    breadcrumb: str


RefusalKind = Literal["not_found", "restricted", "out_of_scope"]


class Meta(_Model):
    type: Literal["meta"] = "meta"
    trace_id: str
    conversation_id: str
    index_version: str
    prompt_version: str
    model_id: str


class Token(_Model):
    type: Literal["token"] = "token"
    text: str


class Citations(_Model):
    type: Literal["citations"] = "citations"
    items: list[Citation]


class Refusal(_Model):
    type: Literal["refusal"] = "refusal"
    kind: RefusalKind
    message: str
    missing_modules: list[str] = []


class Usage(_Model):
    """Internal: a responder reports token counts; folded into Done, never sent."""

    type: Literal["usage"] = "usage"
    usage: TokenUsage


class ErrorEvent(_Model):
    type: Literal["error"] = "error"
    code: str
    message: str


class Done(_Model):
    type: Literal["done"] = "done"
    usage: TokenUsage


ContentEvent = Token | Citations | Refusal | Usage
WireEvent = Meta | Token | Citations | Refusal | ErrorEvent | Done


def to_sse(event: WireEvent) -> bytes:
    data = event.model_dump_json(exclude={"type"})
    return f"event: {event.type}\ndata: {data}\n\n".encode()
