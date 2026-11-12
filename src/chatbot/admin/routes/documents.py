from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel

from chatbot.admin.auth import EditorDep, ViewerDep
from chatbot.admin.models import (
    DocumentDetail,
    DocumentSummary,
    DocumentVersion,
    DocumentVersionContent,
)
from chatbot.admin.routes import http_error, service
from chatbot.admin.service import NotFound
from chatbot.admin.validation import MAX_BYTES, UploadRejected

router = APIRouter()

StaleDays = Annotated[
    int, Query(ge=1, le=3650, description="Live versions older than this are stale.")
]


class Me(BaseModel):
    sub: str
    admin_role: str


@router.get("/me")
async def me(admin: ViewerDep) -> Me:
    return Me(sub=admin.sub, admin_role=admin.role)


@router.get("/documents")
async def list_documents(
    request: Request, _: ViewerDep, stale_days: StaleDays = 90
) -> list[DocumentSummary]:
    return await service(request).documents(stale_days)


@router.get("/documents/{doc_id}")
async def get_document(
    request: Request, doc_id: str, _: ViewerDep, stale_days: StaleDays = 90
) -> DocumentDetail:
    try:
        return await service(request).document(doc_id, stale_days)
    except NotFound as e:
        raise http_error(e) from None


@router.get("/documents/{doc_id}/versions/{version}")
async def get_version(
    request: Request, doc_id: str, version: int, _: ViewerDep
) -> DocumentVersionContent:
    try:
        return await service(request).document_version(doc_id, version)
    except NotFound as e:
        raise http_error(e) from None


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(request: Request, file: UploadFile, admin: EditorDep) -> DocumentVersion:
    raw = await file.read(MAX_BYTES + 1)
    try:
        v = await service(request).upload(file.filename or "", raw, admin.sub)
    except UploadRejected as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, e.errors) from None
    return DocumentVersion(**v.model_dump(exclude={"markdown"}))
