"""Admin domain records. Also the admin API's response contract.

These stay plain data: the mock repository holds them in memory now, the
Postgres repository (stories A1-A2) will map them to rows.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class Job(_Model):
    id: str
    kind: Literal["build_release"]
    status: JobStatus
    progress: JobProgress
    release_id: str | None = None
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
