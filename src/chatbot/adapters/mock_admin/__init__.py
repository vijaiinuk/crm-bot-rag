from datetime import UTC, datetime

from chatbot.adapters.mock_admin.repository import InMemoryAdminRepository, InProcessJobRunner
from chatbot.adapters.mock_admin.seed import seed
from chatbot.admin.service import AdminService


def build_mock_admin_service(known_modules: frozenset[str], *, job_step_s: float) -> AdminService:
    """An AdminService over a freshly seeded in-memory repository."""
    repo = InMemoryAdminRepository()
    seed(repo, datetime.now(UTC))
    return AdminService(repo, InProcessJobRunner(), known_modules, job_step_s=job_step_s)
