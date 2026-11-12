"""In-memory AdminRepository and JobRunner for the admin mock. Resets on restart."""

import asyncio
from collections.abc import Awaitable, Callable

from chatbot.admin.models import AuditEntry, Document, EvalLabelRef, Job, Release


class InMemoryAdminRepository:
    def __init__(self) -> None:
        self.documents: dict[str, Document] = {}
        self.releases: dict[str, Release] = {}
        self.jobs: dict[str, Job] = {}
        self.eval_labels: list[EvalLabelRef] = []
        self.audit: list[AuditEntry] = []
        self._job_seq = 0

    # Copies on the way in and out, so callers can't mutate stored state by accident.

    async def list_documents(self) -> list[Document]:
        return [d.model_copy(deep=True) for d in self.documents.values()]

    async def get_document(self, doc_id: str) -> Document | None:
        d = self.documents.get(doc_id)
        return d.model_copy(deep=True) if d else None

    async def save_document(self, document: Document) -> None:
        self.documents[document.doc_id] = document.model_copy(deep=True)

    async def list_releases(self) -> list[Release]:
        return [r.model_copy(deep=True) for r in self.releases.values()]

    async def get_release(self, release_id: str) -> Release | None:
        r = self.releases.get(release_id)
        return r.model_copy(deep=True) if r else None

    async def save_release(self, release: Release) -> None:
        self.releases[release.id] = release.model_copy(deep=True)

    async def next_release_id(self) -> str:
        numbers = [int(rid[1:]) for rid in self.releases if rid[1:].isdigit()]
        return f"r{max(numbers, default=0) + 1}"

    async def get_job(self, job_id: str) -> Job | None:
        j = self.jobs.get(job_id)
        return j.model_copy(deep=True) if j else None

    async def save_job(self, job: Job) -> None:
        self.jobs[job.id] = job.model_copy(deep=True)

    async def next_job_id(self) -> str:
        self._job_seq += 1
        return f"job-{self._job_seq}"

    async def accepted_eval_labels(self) -> list[EvalLabelRef]:
        return [e.model_copy(deep=True) for e in self.eval_labels]

    async def append_audit(self, entry: AuditEntry) -> None:
        self.audit.append(entry)

    async def list_audit(self) -> list[AuditEntry]:
        return list(self.audit)


class InProcessJobRunner:
    """Runs jobs as asyncio tasks in the API process (stand-in for the worker)."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def start(self, work: Callable[[], Awaitable[None]]) -> None:
        async def run() -> None:
            await work()

        task = asyncio.get_running_loop().create_task(run())
        self._tasks.add(task)  # keep a reference until done
        task.add_done_callback(self._tasks.discard)
