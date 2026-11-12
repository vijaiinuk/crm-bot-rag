"""Costs, conversations, prices and the overview: read-only for every admin role."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request

from chatbot.admin.auth import ViewerDep
from chatbot.admin.models import (
    ConversationDetail,
    ConversationSummary,
    CostSummary,
    ModelPrice,
    Overview,
)
from chatbot.admin.routes import http_error
from chatbot.admin.routes.evals import insights
from chatbot.admin.service import NotFound

router = APIRouter()


@router.get("/overview")
async def overview(request: Request, _: ViewerDep) -> Overview:
    return await insights(request).overview()


@router.get("/costs")
async def costs(
    request: Request, _: ViewerDep, days: Annotated[int, Query(ge=1, le=366)] = 30
) -> CostSummary:
    """Estimated LLM cost for the last `days` days (UTC): tokens at the price on the day."""
    return await insights(request).costs(days)


@router.get("/prices")
async def prices(request: Request, _: ViewerDep) -> list[ModelPrice]:
    return await insights(request).prices()


@router.get("/conversations")
async def list_conversations(
    request: Request,
    _: ViewerDep,
    tenant: str | None = None,
    sort: Literal["recent", "cost"] = "recent",
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[ConversationSummary]:
    return await insights(request).conversations(tenant, sort, limit)


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    request: Request, conversation_id: str, _: ViewerDep
) -> ConversationDetail:
    """Redacted transcript plus the LLM calls (and estimated cost) behind each turn."""
    try:
        return await insights(request).conversation(conversation_id)
    except NotFound as e:
        raise http_error(e) from None
