import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

from chatbot.adapters.local_entitlements import LocalEntitlementProvider
from chatbot.api.app import create_app
from chatbot.api.auth import HttpJwksSource
from chatbot.config import Settings
from tests.conftest import PERSONAS, MintToken

AdminHeaders = Callable[[str], dict[str, str]]


@pytest.fixture
def admin_headers(mint: MintToken) -> AdminHeaders:
    """Bearer headers for an ops admin with the given admin_role."""

    def _headers(admin_role: str) -> dict[str, str]:
        token = mint(
            sub=f"admin-{admin_role}",
            tenant="ops",
            role="ops_admin",
            extra_claims={"admin_role": admin_role},
        )
        return {"Authorization": f"Bearer {token}"}

    return _headers


async def make_admin_client(
    settings: Settings, jwks_source: HttpJwksSource
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        settings, jwks_source=jwks_source, entitlements=LocalEntitlementProvider(PERSONAS)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test"
    ) as c:
        yield c


@pytest.fixture
async def admin_client(
    settings: Settings, jwks_source: HttpJwksSource
) -> AsyncIterator[httpx.AsyncClient]:
    async for c in make_admin_client(settings, jwks_source):
        yield c


async def wait_for_job(
    client: httpx.AsyncClient, job_id: str, headers: dict[str, str]
) -> dict[str, Any]:
    for _ in range(500):
        job = (await client.get(f"/admin/jobs/{job_id}", headers=headers)).json()
        if job["status"] in ("succeeded", "failed"):
            return job  # type: ignore[no-any-return]
        await asyncio.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish")
