from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field

from chatbot.admin.auth import EditorDep, PublisherDep, ViewerDep
from chatbot.admin.models import AuditEntry, DraftDiff, Job, Release
from chatbot.admin.routes import http_error, service
from chatbot.admin.service import Conflict, NotFound

router = APIRouter()


class DraftDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class PublishAccepted(BaseModel):
    job_id: str
    release_id: str


@router.get("/releases")
async def list_releases(request: Request, _: ViewerDep) -> list[Release]:
    return await service(request).releases()


# The draft routes come before /releases/{release_id} so "draft" isn't read as an id.
@router.get("/releases/draft")
async def get_draft(request: Request, _: ViewerDep) -> Release:
    return await service(request).draft()


@router.get("/releases/draft/diff")
async def get_draft_diff(request: Request, _: ViewerDep) -> DraftDiff:
    return await service(request).draft_diff()


@router.put("/releases/draft/documents/{doc_id}")
async def set_draft_document(
    request: Request, doc_id: str, body: DraftDocument, admin: EditorDep
) -> Release:
    try:
        return await service(request).set_draft_document(doc_id, body.version, admin.sub)
    except (NotFound, Conflict) as e:
        raise http_error(e) from None


@router.delete("/releases/draft/documents/{doc_id}")
async def remove_draft_document(request: Request, doc_id: str, admin: EditorDep) -> Release:
    try:
        return await service(request).remove_draft_document(doc_id, admin.sub)
    except NotFound as e:
        raise http_error(e) from None


@router.get("/releases/{release_id}")
async def get_release(request: Request, release_id: str, _: ViewerDep) -> Release:
    try:
        return await service(request).release(release_id)
    except NotFound as e:
        raise http_error(e) from None


@router.post("/releases/{release_id}/publish", status_code=status.HTTP_202_ACCEPTED)
async def publish(request: Request, release_id: str, admin: PublisherDep) -> PublishAccepted:
    try:
        job = await service(request).publish(release_id, admin.sub)
    except (NotFound, Conflict) as e:
        raise http_error(e) from None
    return PublishAccepted(job_id=job.id, release_id=release_id)


@router.post("/releases/{release_id}/confirm")
async def confirm(request: Request, release_id: str, admin: PublisherDep) -> Release:
    """Accept a release whose modules widen access. Audit-logged."""
    try:
        return await service(request).confirm(release_id, admin.sub)
    except (NotFound, Conflict) as e:
        raise http_error(e) from None


@router.post("/releases/{release_id}/rollback")
async def rollback(request: Request, release_id: str, admin: PublisherDep) -> Release:
    """Make a previously live release live again."""
    try:
        return await service(request).rollback(release_id, admin.sub)
    except (NotFound, Conflict) as e:
        raise http_error(e) from None


@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str, _: ViewerDep) -> Job:
    try:
        return await service(request).job(job_id)
    except NotFound as e:
        raise http_error(e) from None


@router.get("/audit")
async def audit(request: Request, _: ViewerDep) -> list[AuditEntry]:
    return await service(request).audit_log()
