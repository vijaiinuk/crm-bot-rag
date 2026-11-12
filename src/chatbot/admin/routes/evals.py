from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from chatbot.admin.auth import EditorDep, PublisherDep, ViewerDep
from chatbot.admin.insights import AdminInsights, Invalid
from chatbot.admin.models import (
    EvalQuestion,
    EvalQuestionCreate,
    EvalQuestionPatch,
    EvalResult,
    EvalRun,
    EvalRunDetail,
    LabelRequest,
)
from chatbot.admin.routes import http_error
from chatbot.admin.service import Conflict, NotFound

router = APIRouter()


def insights(request: Request) -> AdminInsights:
    i: AdminInsights = request.app.state.insights
    return i


def invalid(e: Invalid) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, e.errors)


class JobAccepted(BaseModel):
    job_id: str


class RunAccepted(JobAccepted):
    run_id: str


@router.get("/eval-questions")
async def list_questions(
    request: Request,
    _: ViewerDep,
    status_: Annotated[
        Literal["proposed", "accepted", "rejected"] | None, Query(alias="status")
    ] = None,
    source: Literal["admin", "synthetic", "redteam", "file"] | None = None,
) -> list[EvalQuestion]:
    return await insights(request).questions(status_, source)


@router.post("/eval-questions", status_code=status.HTTP_201_CREATED)
async def create_question(
    request: Request, body: EvalQuestionCreate, admin: EditorDep
) -> EvalQuestion:
    try:
        return await insights(request).create_question(body, admin.sub)
    except Invalid as e:
        raise invalid(e) from None


@router.get("/eval-questions/{question_id}")
async def get_question(request: Request, question_id: str, _: ViewerDep) -> EvalQuestion:
    try:
        return await insights(request).question(question_id)
    except NotFound as e:
        raise http_error(e) from None


@router.patch("/eval-questions/{question_id}")
async def update_question(
    request: Request, question_id: str, body: EvalQuestionPatch, admin: EditorDep
) -> EvalQuestion:
    try:
        return await insights(request).update_question(question_id, body, admin.sub)
    except NotFound as e:
        raise http_error(e) from None
    except Invalid as e:
        raise invalid(e) from None


@router.post("/eval-questions/{question_id}/accept")
async def accept_question(request: Request, question_id: str, admin: EditorDep) -> EvalQuestion:
    try:
        return await insights(request).review_question(question_id, True, admin.sub)
    except (NotFound, Conflict) as e:
        raise http_error(e) from None


@router.post("/eval-questions/{question_id}/reject")
async def reject_question(request: Request, question_id: str, admin: EditorDep) -> EvalQuestion:
    try:
        return await insights(request).review_question(question_id, False, admin.sub)
    except (NotFound, Conflict) as e:
        raise http_error(e) from None


@router.post("/documents/{doc_id}/synthetic-questions", status_code=status.HTTP_202_ACCEPTED)
async def generate_synthetic(request: Request, doc_id: str, admin: EditorDep) -> JobAccepted:
    """Propose eval questions for a doc. They count only once an editor accepts them."""
    try:
        job = await insights(request).start_synthetic(doc_id, admin.sub)
    except NotFound as e:
        raise http_error(e) from None
    return JobAccepted(job_id=job.id)


@router.get("/eval-runs")
async def list_runs(request: Request, _: ViewerDep) -> list[EvalRun]:
    return await insights(request).runs()


@router.post("/eval-runs", status_code=status.HTTP_202_ACCEPTED)
async def start_run(request: Request, admin: PublisherDep) -> RunAccepted:
    """Start an end-to-end eval run (LLM + judge). Manual: it costs money."""
    try:
        job, run_id = await insights(request).start_run(admin.sub)
    except Conflict as e:
        raise http_error(e) from None
    return RunAccepted(job_id=job.id, run_id=run_id)


@router.get("/eval-runs/{run_id}")
async def get_run(request: Request, run_id: str, _: ViewerDep) -> EvalRunDetail:
    try:
        return await insights(request).run(run_id)
    except NotFound as e:
        raise http_error(e) from None


@router.put("/eval-results/{result_id}/label")
async def label_result(
    request: Request, result_id: str, body: LabelRequest, admin: EditorDep
) -> EvalResult:
    try:
        return await insights(request).label_result(result_id, body, admin.sub)
    except NotFound as e:
        raise http_error(e) from None
