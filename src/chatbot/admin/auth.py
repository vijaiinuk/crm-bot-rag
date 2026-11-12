"""Admin access: identity and role come only from the verified JWT.

An admin token carries `tenant` = the configured ops tenant and an `admin_role`
claim. Anything else (including every client-company token) gets 403.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from chatbot.api.auth import AuthContext, Bearer, authenticate

log = logging.getLogger(__name__)


class AdminRole(StrEnum):
    viewer = "viewer"
    editor = "editor"
    publisher = "publisher"


_RANK = {AdminRole.viewer: 0, AdminRole.editor: 1, AdminRole.publisher: 2}


@dataclass(frozen=True, slots=True)
class Admin:
    sub: str
    role: AdminRole

    def can(self, minimum: AdminRole) -> bool:
        return _RANK[self.role] >= _RANK[minimum]


def _forbidden(detail: str = "admin role required") -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail)


async def current_admin(request: Request, creds: Bearer) -> Admin:
    claims = await authenticate(request, creds)
    ctx: AuthContext = request.app.state.auth
    raw_role = claims.raw.get("admin_role")
    if claims.principal.tenant != ctx.settings.admin_tenant or not isinstance(raw_role, str):
        log.info("admin access denied for %s@%s", claims.principal.role, claims.principal.tenant)
        raise _forbidden()
    try:
        role = AdminRole(raw_role)
    except ValueError:
        raise _forbidden() from None
    return Admin(sub=claims.principal.sub, role=role)


def require(minimum: AdminRole) -> Callable[[Admin], Awaitable[Admin]]:
    async def check(admin: Annotated[Admin, Depends(current_admin)]) -> Admin:
        if not admin.can(minimum):
            raise _forbidden(f"{minimum} role required")
        return admin

    return check


ViewerDep = Annotated[Admin, Depends(current_admin)]
EditorDep = Annotated[Admin, Depends(require(AdminRole.editor))]
PublisherDep = Annotated[Admin, Depends(require(AdminRole.publisher))]
