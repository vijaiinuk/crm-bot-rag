"""In-memory AdminRepository, ConversationStore and JobRunner for the mock. Resets on restart."""

import asyncio
import itertools
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from chatbot.admin.conversations import turn_rows
from chatbot.admin.models import (
    AuditEntry,
    ConversationRecord,
    Document,
    EvalLabelRef,
    EvalQuestion,
    EvalResult,
    EvalRun,
    Job,
    LlmCall,
    Message,
    ModelPrice,
    QuestionStatus,
    Release,
)
from chatbot.ports.conversations import ChatTurn
from chatbot.ports.entitlements import Principal

log = logging.getLogger(__name__)


class InMemoryAdminRepository:
    def __init__(self) -> None:
        self.documents: dict[str, Document] = {}
        self.releases: dict[str, Release] = {}
        self.jobs: dict[str, Job] = {}
        self.questions: dict[str, EvalQuestion] = {}
        self.runs: dict[str, EvalRun] = {}
        self.results: dict[str, list[EvalResult]] = {}
        self.conversations: dict[str, ConversationRecord] = {}
        self.messages: list[Message] = []
        self.llm_calls: list[LlmCall] = []
        self.prices: list[ModelPrice] = []
        self.audit: list[AuditEntry] = []
        self._seq = itertools.count(1)

    def next_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._seq)}"

    # Copies on the way in and out, so callers can't mutate stored state by accident.

    # --- documents and releases ---------------------------------------------------

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
        return self.next_id("job")

    # --- evals ----------------------------------------------------------------------

    async def accepted_eval_labels(self) -> list[EvalLabelRef]:
        return [
            EvalLabelRef(question_id=q.id, labels=q.labels)
            for q in self.questions.values()
            if q.status == QuestionStatus.accepted
        ]

    async def list_questions(self) -> list[EvalQuestion]:
        return [q.model_copy(deep=True) for q in self.questions.values()]

    async def get_question(self, question_id: str) -> EvalQuestion | None:
        q = self.questions.get(question_id)
        return q.model_copy(deep=True) if q else None

    async def save_question(self, question: EvalQuestion) -> None:
        self.questions[question.id] = question.model_copy(deep=True)

    async def next_question_id(self) -> str:
        numbers = [int(q[2:]) for q in self.questions if q[2:].isdigit()]
        return f"q-{max(numbers, default=0) + 1:04d}"

    async def list_runs(self) -> list[EvalRun]:
        return [r.model_copy(deep=True) for r in self.runs.values()]

    async def get_run(self, run_id: str) -> EvalRun | None:
        r = self.runs.get(run_id)
        return r.model_copy(deep=True) if r else None

    async def save_run(self, run: EvalRun) -> None:
        self.runs[run.id] = run.model_copy(deep=True)

    async def next_run_id(self) -> str:
        return f"e-{len(self.runs) + 1}"

    async def list_results(self, run_id: str) -> list[EvalResult]:
        return [r.model_copy(deep=True) for r in self.results.get(run_id, [])]

    async def save_results(self, run_id: str, results: list[EvalResult]) -> None:
        self.results[run_id] = [r.model_copy(deep=True) for r in results]

    # --- conversations and cost ---------------------------------------------------

    async def list_conversations(self) -> list[ConversationRecord]:
        return [c.model_copy() for c in self.conversations.values()]

    async def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        c = self.conversations.get(conversation_id)
        return c.model_copy() if c else None

    async def list_messages(self, conversation_id: str | None = None) -> list[Message]:
        return [
            m.model_copy() for m in self.messages if conversation_id in (None, m.conversation_id)
        ]

    async def list_llm_calls(self) -> list[LlmCall]:
        return [c.model_copy() for c in self.llm_calls]

    async def add_llm_calls(self, calls: list[LlmCall]) -> None:
        self.llm_calls.extend(c.model_copy() for c in calls)

    async def list_prices(self) -> list[ModelPrice]:
        return [p.model_copy() for p in self.prices]

    def price_for(self, model_id: str, at: datetime) -> ModelPrice | None:
        """The price in effect for `model_id` at `at`."""
        candidates = [p for p in self.prices if p.model_id == model_id and p.valid_from <= at]
        return max(candidates, key=lambda p: p.valid_from, default=None)

    # --- ConversationStore ------------------------------------------------------------

    async def open_conversation(
        self, conversation_id: str | None, principal: Principal, at: datetime
    ) -> str | None:
        if conversation_id is None:
            new_id = str(uuid.uuid4())
            self.conversations[new_id] = ConversationRecord(
                conversation_id=new_id,
                sub=principal.sub,
                tenant=principal.tenant,
                role=principal.role,
                created_at=at,
                last_active_at=at,
            )
            return new_id
        c = self.conversations.get(conversation_id)
        if c is None or (c.sub, c.tenant) != (principal.sub, principal.tenant):
            return None
        return conversation_id

    def record_turn(self, turn: ChatTurn) -> None:
        conv = self.conversations.get(turn.trace.conversation_id)
        if conv is None:  # opened by this request, so this means a bug, not a user error
            log.error("record_turn for unknown conversation %s", turn.trace.conversation_id)
            return
        messages, calls = turn_rows(
            turn, self.price_for(turn.trace.model_id, turn.at), self.next_id
        )
        self.messages.extend(messages)
        self.llm_calls.extend(calls)
        conv.last_active_at = turn.at

    # --- audit --------------------------------------------------------------------------

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
