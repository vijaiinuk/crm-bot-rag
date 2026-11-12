"""Admin business rules: documents, the draft release, publishing and the gate.

Storage and background execution are ports, so these rules carry over unchanged
when the in-memory mock is replaced by Postgres and the job-queue worker.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from chatbot.admin.models import (
    AuditEntry,
    Document,
    DocumentDetail,
    DocumentSummary,
    DocumentVersion,
    DocumentVersionContent,
    DraftDiff,
    GateCheck,
    GateReport,
    Job,
    JobProgress,
    JobStatus,
    Release,
    ReleaseStatus,
    VersionStatus,
)
from chatbot.admin.releases import gate_outcome, module_diff, orphaned_labels
from chatbot.admin.validation import parse_upload
from chatbot.ports.admin import AdminRepository, JobRunner

log = logging.getLogger(__name__)

BUILD_STAGES = [("chunking", 20), ("embedding", 45), ("indexing", 70), ("gate", 90)]
IN_FLIGHT = {ReleaseStatus.building, ReleaseStatus.gate}


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class AdminService:
    def __init__(
        self,
        repo: AdminRepository,
        jobs: JobRunner,
        known_modules: frozenset[str],
        *,
        job_step_s: float = 0.8,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.repo = repo
        self.jobs = jobs
        self.known_modules = known_modules
        self.job_step_s = job_step_s
        self.clock = clock
        # Serialises publish/confirm/rollback so two requests can't both win a race.
        self._lock = asyncio.Lock()

    # --- documents --------------------------------------------------------------

    async def documents(self, stale_days: int) -> list[DocumentSummary]:
        live, draft = await self._live(), await self.draft()
        docs = await self.repo.list_documents()
        return [
            self._summary(d, live, draft, stale_days) for d in sorted(docs, key=lambda d: d.doc_id)
        ]

    async def document(self, doc_id: str, stale_days: int) -> DocumentDetail:
        doc = await self._document(doc_id)
        summary = self._summary(doc, await self._live(), await self.draft(), stale_days)
        versions = [DocumentVersion(**v.model_dump(exclude={"markdown"})) for v in doc.versions]
        return DocumentDetail(**summary.model_dump(), versions=versions)

    async def document_version(self, doc_id: str, version: int) -> DocumentVersionContent:
        v = (await self._document(doc_id)).version(version)
        if v is None:
            raise NotFound(f"{doc_id} has no version {version}")
        return v

    async def upload(self, filename: str, raw: bytes, actor: str) -> DocumentVersionContent:
        parsed = parse_upload(filename, raw, self.known_modules)
        doc = await self.repo.get_document(parsed.doc_id) or Document(doc_id=parsed.doc_id)
        version = DocumentVersionContent(
            doc_id=parsed.doc_id,
            version=len(doc.versions) + 1,
            title=parsed.title or (doc.latest.title if doc.versions else parsed.doc_id),
            modules=parsed.modules,
            anchors=parsed.anchors,
            status=VersionStatus.rejected if parsed.errors else VersionStatus.validated,
            validation_errors=parsed.errors,
            uploaded_by=actor,
            uploaded_at=self.clock(),
            content_sha256=parsed.content_sha256,
            size_bytes=parsed.size_bytes,
            markdown=parsed.markdown,
        )
        doc.versions.append(version)
        await self.repo.save_document(doc)
        await self._audit(
            actor, "upload", f"{doc.doc_id} v{version.version}", status=version.status
        )
        return version

    # --- the draft --------------------------------------------------------------

    async def draft(self) -> Release:
        """The single open draft; created from the live release if none exists."""
        for r in await self.repo.list_releases():
            if r.status == ReleaseStatus.draft:
                return r
        live = await self._live()
        draft = Release(
            id=await self.repo.next_release_id(),
            status=ReleaseStatus.draft,
            documents=dict(live.documents) if live else {},
            created_by="system",
            created_at=self.clock(),
        )
        await self.repo.save_release(draft)
        return draft

    async def set_draft_document(self, doc_id: str, version: int, actor: str) -> Release:
        v = (await self._document(doc_id)).version(version)
        if v is None:
            raise NotFound(f"{doc_id} has no version {version}")
        if v.status != VersionStatus.validated:
            raise Conflict(f"{doc_id} v{version} failed validation and can't be released")
        draft = await self.draft()
        draft.documents[doc_id] = version
        await self.repo.save_release(draft)
        await self._audit(actor, "draft.set", doc_id, version=version)
        return draft

    async def remove_draft_document(self, doc_id: str, actor: str) -> Release:
        draft = await self.draft()
        if draft.documents.pop(doc_id, None) is None:
            raise NotFound(f"{doc_id} is not in the draft")
        await self.repo.save_release(draft)
        await self._audit(actor, "draft.remove", doc_id)
        return draft

    async def draft_diff(self) -> DraftDiff:
        report = await self._gate_inputs(await self.draft())
        return DraftDiff(
            module_changes=report.module_changes, orphaned_labels=report.orphaned_labels
        )

    # --- releases ---------------------------------------------------------------

    async def releases(self) -> list[Release]:
        await self.draft()  # make sure a draft is always listed
        return sorted(await self.repo.list_releases(), key=lambda r: int(r.id[1:]), reverse=True)

    async def release(self, release_id: str) -> Release:
        r = await self.repo.get_release(release_id)
        if r is None:
            raise NotFound(f"no release {release_id}")
        return r

    async def publish(self, release_id: str, actor: str) -> Job:
        async with self._lock:
            release = await self.release(release_id)
            if release.status != ReleaseStatus.draft:
                raise Conflict(f"{release_id} is {release.status}; only the draft can be published")
            if any(r.status in IN_FLIGHT for r in await self.repo.list_releases()):
                raise Conflict("another release is still building")
            if not release.documents:
                raise Conflict("the draft has no documents")

            now = self.clock()
            job = Job(
                id=await self.repo.next_job_id(),
                kind="build_release",
                status=JobStatus.queued,
                progress=JobProgress(stage="queued", pct=0),
                release_id=release.id,
                created_at=now,
            )
            release.status, release.published_by, release.published_at, release.job_id = (
                ReleaseStatus.building,
                actor,
                now,
                job.id,
            )
            await self.repo.save_job(job)
            await self.repo.save_release(release)
            # Editing continues on a fresh draft with the same contents.
            await self.repo.save_release(
                Release(
                    id=await self.repo.next_release_id(),
                    status=ReleaseStatus.draft,
                    documents=dict(release.documents),
                    created_by=actor,
                    created_at=now,
                )
            )
            await self._audit(actor, "release.publish", release.id, job=job.id)

        self.jobs.start(lambda: self._build(release.id, job.id))
        return job

    async def confirm(self, release_id: str, actor: str) -> Release:
        async with self._lock:
            release = await self.release(release_id)
            if release.status != ReleaseStatus.awaiting_confirmation:
                raise Conflict(f"{release_id} is {release.status}, not awaiting confirmation")
            release.confirmed_by = actor
            await self._make_live(release)
            widened = [
                c.doc_id
                for c in (release.gate_report.module_changes if release.gate_report else [])
                if c.change == "widened"
            ]
            await self._audit(actor, "release.confirm_widening", release.id, widened=widened)
            return await self.release(release_id)

    async def rollback(self, release_id: str, actor: str) -> Release:
        async with self._lock:
            release = await self.release(release_id)
            if release.status != ReleaseStatus.superseded:
                raise Conflict(
                    f"{release_id} is {release.status}; only a past live release can be restored"
                )
            previous = await self._live()
            await self._make_live(release)
            await self._audit(
                actor, "release.rollback", release.id, previous=previous.id if previous else None
            )
            return await self.release(release_id)

    async def job(self, job_id: str) -> Job:
        j = await self.repo.get_job(job_id)
        if j is None:
            raise NotFound(f"no job {job_id}")
        return j

    async def audit_log(self) -> list[AuditEntry]:
        return list(reversed(await self.repo.list_audit()))

    # --- the build job ------------------------------------------------------------

    async def _build(self, release_id: str, job_id: str) -> None:
        job = await self.job(job_id)
        try:
            job.status = JobStatus.running
            for stage, pct in BUILD_STAGES:
                job.progress = JobProgress(stage=stage, pct=pct)
                await self.repo.save_job(job)
                if stage == "gate":
                    await self._set_status(release_id, ReleaseStatus.gate)
                await asyncio.sleep(self.job_step_s)

            async with self._lock:
                release = await self.release(release_id)
                release.gate_report = await self._gate_inputs(release)
                outcome = gate_outcome(release.gate_report.checks)
                if outcome == ReleaseStatus.live:
                    await self._make_live(release)
                else:
                    release.status = outcome
                    await self.repo.save_release(release)
            job.status, job.progress = JobStatus.succeeded, JobProgress(stage="done", pct=100)
        except Exception as e:  # a crashed build must never leave a release half-live
            log.exception("build_release %s failed", release_id)
            job.status, job.error = JobStatus.failed, f"{type(e).__name__}: build failed"
            await self._set_status(release_id, ReleaseStatus.failed)
        job.finished_at = self.clock()
        await self.repo.save_job(job)

    async def _gate_inputs(self, release: Release) -> GateReport:
        live = await self._live()
        docs = {d.doc_id: d for d in await self.repo.list_documents()}

        def contents(r: Release | None) -> dict[str, DocumentVersionContent]:
            if r is None:
                return {}
            out = {}
            for doc_id, n in r.documents.items():
                v = docs[doc_id].version(n) if doc_id in docs else None
                if v is None:  # fail closed: a release can't reference a missing version
                    raise Conflict(f"{r.id} references {doc_id} v{n}, which doesn't exist")
                out[doc_id] = v
            return out

        live_docs, release_docs = contents(live), contents(release)
        anchors = {doc_id: set(v.anchors) for doc_id, v in release_docs.items()}
        changes = module_diff(
            {d: v.modules for d, v in live_docs.items()},
            {d: v.modules for d, v in release_docs.items()},
        )
        orphans = orphaned_labels(
            ((q.question_id, q.labels) for q in await self.repo.accepted_eval_labels()), anchors
        )
        widened = [c.doc_id for c in changes if c.change == "widened"]
        checks = [
            GateCheck(
                name="permission_suite",
                status="pass",
                detail="Mock: passes until the real permission suite (S2.3.2) runs here.",
            ),
            GateCheck(
                name="retrieval_evals",
                status="pass",
                detail="Mock: no retrieval yet, so recall can't regress.",
            ),
            GateCheck(
                name="orphaned_labels",
                status="fail" if orphans else "pass",
                detail=f"{len(orphans)} eval label(s) point at sections that no longer exist."
                if orphans
                else "Every eval label points at an existing section.",
            ),
            GateCheck(
                name="access_widening",
                status="needs_confirmation" if widened else "pass",
                detail=f"More users would see: {', '.join(widened)}. A publisher must confirm."
                if widened
                else "No document becomes visible to more users.",
            ),
        ]
        return GateReport(module_changes=changes, orphaned_labels=orphans, checks=checks)

    # --- helpers --------------------------------------------------------------------

    async def _live(self) -> Release | None:
        return next(
            (r for r in await self.repo.list_releases() if r.status == ReleaseStatus.live), None
        )

    async def _make_live(self, release: Release) -> None:
        current = await self._live()
        if current and current.id != release.id:
            current.status = ReleaseStatus.superseded
            await self.repo.save_release(current)
        release.status, release.live_since = ReleaseStatus.live, self.clock()
        await self.repo.save_release(release)

    async def _set_status(self, release_id: str, status: ReleaseStatus) -> None:
        release = await self.release(release_id)
        release.status = status
        await self.repo.save_release(release)

    async def _document(self, doc_id: str) -> Document:
        doc = await self.repo.get_document(doc_id)
        if doc is None:
            raise NotFound(f"no document {doc_id}")
        return doc

    async def _audit(self, actor: str, action: str, subject: str, **details: object) -> None:
        await self.repo.append_audit(
            AuditEntry(
                at=self.clock(), actor=actor, action=action, subject=subject, details=details
            )
        )

    def _summary(
        self, doc: Document, live: Release | None, draft: Release, stale_days: int
    ) -> DocumentSummary:
        live_v = live.documents.get(doc.doc_id) if live else None
        live_version = doc.version(live_v) if live_v else None
        shown = live_version or doc.latest
        stale = bool(
            live_version and self.clock() - live_version.uploaded_at > timedelta(days=stale_days)
        )
        return DocumentSummary(
            doc_id=doc.doc_id,
            title=shown.title,
            latest_version=doc.latest.version,
            latest_status=doc.latest.status,
            live_version=live_v,
            draft_version=draft.documents.get(doc.doc_id),
            modules=shown.modules,
            updated_at=doc.latest.uploaded_at,
            live_uploaded_at=live_version.uploaded_at if live_version else None,
            stale=stale,
        )
