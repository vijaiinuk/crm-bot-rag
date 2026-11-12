"""Admin domain records. Also the admin API's response contract.

These stay plain data: the mock repository holds them in memory now, the
Postgres repository (stories A1-A2) will map them to rows.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionStatus(StrEnum):
    validated = "validated"
    rejected = "rejected"


class DocumentVersion(_Model):
    doc_id: str
    version: int
    title: str
    modules: list[str]
    anchors: list[str]
    status: VersionStatus
    validation_errors: list[str] = []
    uploaded_by: str
    uploaded_at: datetime
    content_sha256: str
    size_bytes: int


class DocumentVersionContent(DocumentVersion):
    markdown: str


class Document(_Model):
    doc_id: str
    versions: list[DocumentVersionContent] = Field(default_factory=list)

    def version(self, n: int) -> DocumentVersionContent | None:
        return next((v for v in self.versions if v.version == n), None)

    @property
    def latest(self) -> DocumentVersionContent:
        return self.versions[-1]


class DocumentSummary(_Model):
    doc_id: str
    title: str
    latest_version: int
    latest_status: VersionStatus
    live_version: int | None
    draft_version: int | None
    modules: list[str] = Field(description="Modules of the live version, else of the latest.")
    updated_at: datetime
    live_uploaded_at: datetime | None
    stale: bool


class DocumentDetail(DocumentSummary):
    versions: list[DocumentVersion]


class ReleaseStatus(StrEnum):
    draft = "draft"
    building = "building"
    gate = "gate"
    awaiting_confirmation = "awaiting_confirmation"
    live = "live"
    superseded = "superseded"
    failed = "failed"


ChangeKind = Literal["new", "widened", "narrowed", "unchanged", "retired"]


class ModuleChange(_Model):
    doc_id: str
    change: ChangeKind
    before: list[str] | None
    after: list[str] | None
    dropped: list[str] = []
    added: list[str] = []


class OrphanedLabel(_Model):
    question_id: str
    label: str


CheckStatus = Literal["pass", "fail", "needs_confirmation"]


class GateCheck(_Model):
    name: str
    status: CheckStatus
    detail: str


class DraftDiff(_Model):
    module_changes: list[ModuleChange]
    orphaned_labels: list[OrphanedLabel]


class GateReport(DraftDiff):
    checks: list[GateCheck]


class Release(_Model):
    id: str
    status: ReleaseStatus
    documents: dict[str, int] = Field(description="doc_id -> version")
    created_by: str
    created_at: datetime
    published_by: str | None = None
    published_at: datetime | None = None
    confirmed_by: str | None = None
    live_since: datetime | None = None
    gate_report: GateReport | None = None
    job_id: str | None = None


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class JobProgress(_Model):
    stage: str
    pct: int


JobKind = Literal["build_release", "generate_synthetic_evals", "run_e2e_eval"]


class Job(_Model):
    id: str
    kind: JobKind
    status: JobStatus
    progress: JobProgress
    release_id: str | None = None
    run_id: str | None = None
    doc_id: str | None = None
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class AuditEntry(_Model):
    at: datetime
    actor: str
    action: str
    subject: str
    details: dict[str, object] = {}


class EvalLabelRef(_Model):
    """The part of an eval question the publish gate needs (AD2 adds the rest)."""

    question_id: str
    labels: list[str]


# --- evals ---------------------------------------------------------------------------

Outcome = Literal["answer", "restricted", "not_found", "out_of_scope"]
Category = Literal[
    "single", "multi_hop", "unanswerable", "out_of_scope", "restricted", "adversarial"
]
QuestionSource = Literal["admin", "synthetic", "redteam", "file"]


class Expected(_Model):
    """What one persona should get. Same shape as evals/golden/*.yaml."""

    outcome: Outcome
    required: list[str] = Field(default_factory=list, description="doc_id#anchor labels")
    missing_modules: list[str] = Field(default_factory=list)


class QuestionStatus(StrEnum):
    proposed = "proposed"
    accepted = "accepted"
    rejected = "rejected"


class EvalQuestion(_Model):
    id: str
    question: str
    category: Category
    expected: dict[str, Expected] = Field(description="persona -> expected outcome")
    status: QuestionStatus
    source: QuestionSource
    created_by: str
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def labels(self) -> list[str]:
        return sorted({lbl for e in self.expected.values() for lbl in e.required})


class EvalQuestionCreate(_Model):
    question: str = Field(min_length=5, max_length=500)
    category: Category
    expected: dict[str, Expected] = Field(min_length=1)


class EvalQuestionPatch(_Model):
    question: str | None = Field(default=None, min_length=5, max_length=500)
    category: Category | None = None
    expected: dict[str, Expected] | None = Field(default=None, min_length=1)


class LabelRequest(_Model):
    faithful: bool
    correct: bool


class EvalLabel(LabelRequest):
    labeller: str
    at: datetime


class EvalResult(_Model):
    id: str
    run_id: str
    question_id: str
    question: str
    persona: str
    expected_outcome: Outcome
    actual_outcome: Outcome
    answer: str
    judge_faithful: bool
    judge_correct: bool
    citations_ok: bool
    label: EvalLabel | None = None


class EvalMetrics(_Model):
    faithfulness: float
    correctness: float
    refusal_accuracy: float
    citation_accuracy: float


class JudgeAgreement(_Model):
    labelled: int
    faithful_agreement: float | None
    correct_agreement: float | None


class RunStatus(StrEnum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class EvalRun(_Model):
    id: str
    status: RunStatus
    started_by: str
    started_at: datetime
    finished_at: datetime | None = None
    release_id: str | None
    answer_model: str
    judge_model: str
    prompt_version: str
    questions: int = 0
    metrics: EvalMetrics | None = None
    cost_usd: float = 0.0
    job_id: str | None = None


class EvalRunDetail(EvalRun):
    results: list[EvalResult]
    judge_agreement: JudgeAgreement


# --- conversations and cost -------------------------------------------------------------

Bucket = Literal["chat", "eval", "ingest"]
Stage = Literal["rewrite", "generate", "judge", "synth"]


class ModelPrice(_Model):
    price_id: str
    model_id: str
    provider: str
    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float
    valid_from: datetime
    note: str = ""


class LlmCall(_Model):
    id: str
    trace_id: str
    conversation_id: str | None
    tenant: str | None
    bucket: Bucket
    stage: Stage
    model_id: str
    provider: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    price_id: str
    cost_usd: float
    latency_ms: float
    created_at: datetime


class ConversationRecord(_Model):
    conversation_id: str
    sub: str
    tenant: str
    role: str
    created_at: datetime
    last_active_at: datetime


class Message(_Model):
    id: str
    conversation_id: str
    trace_id: str
    role: Literal["user", "assistant"]
    content: str = Field(description="Redacted before storage.")
    outcome: str | None = None
    created_at: datetime


class ConversationSummary(ConversationRecord):
    turns: int
    last_outcome: str | None
    cost_usd: float


class ConversationDetail(ConversationSummary):
    messages: list[Message]
    llm_calls: list[LlmCall]


class TenantMonth(_Model):
    tenant: str
    month: str
    cost_usd: float
    calls: int


class ModelCost(_Model):
    model_id: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class DailyCost(_Model):
    date: date
    chat: float
    eval: float
    ingest: float


class ConversationCost(_Model):
    conversation_id: str
    tenant: str | None
    cost_usd: float


class CostSummary(_Model):
    start: date
    end: date
    estimated: bool = True
    total_usd: float
    by_bucket: dict[str, float]
    by_tenant_month: list[TenantMonth]
    by_model: list[ModelCost]
    daily: list[DailyCost]
    top_conversations: list[ConversationCost]


class Overview(_Model):
    live_release: Release | None
    draft_release: Release
    last_published: Release | None
    documents: int
    stale_documents: int
    proposed_questions: int
    accepted_questions: int
    last_eval_run: EvalRun | None
    month_to_date_usd: float
    conversations_7d: int
