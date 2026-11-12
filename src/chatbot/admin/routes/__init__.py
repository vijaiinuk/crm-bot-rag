from fastapi import APIRouter, HTTPException, Request, status

from chatbot.admin.service import AdminService, Conflict, NotFound


def service(request: Request) -> AdminService:
    svc: AdminService = request.app.state.admin
    return svc


def http_error(e: NotFound | Conflict) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if isinstance(e, NotFound) else status.HTTP_409_CONFLICT
    return HTTPException(code, str(e))


def build_admin_router() -> APIRouter:
    from chatbot.admin.routes import documents, releases

    router = APIRouter(prefix="/admin", tags=["admin"])
    router.include_router(documents.router)
    router.include_router(releases.router)
    return router
