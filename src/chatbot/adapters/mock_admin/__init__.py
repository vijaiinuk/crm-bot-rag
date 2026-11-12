from collections.abc import Mapping
from datetime import UTC, datetime

from chatbot.adapters.mock_admin.repository import InMemoryAdminRepository, InProcessJobRunner
from chatbot.adapters.mock_admin.seed import seed
from chatbot.admin import AdminBundle
from chatbot.admin.insights import AdminInsights
from chatbot.admin.service import AdminService


def build_mock_admin(
    known_modules: frozenset[str],
    *,
    personas: Mapping[str, frozenset[str]] | None = None,
    job_step_s: float,
) -> AdminBundle:
    """Admin services over one freshly seeded in-memory repository, which also
    stores chat conversations so live chats show up in the dashboard."""
    repo = InMemoryAdminRepository()
    seed(repo, datetime.now(UTC))
    service = AdminService(repo, InProcessJobRunner(), known_modules, job_step_s=job_step_s)
    return AdminBundle(
        service=service, insights=AdminInsights(service, personas or {}), conversations=repo
    )
