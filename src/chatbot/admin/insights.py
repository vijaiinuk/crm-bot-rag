"""Admin read models and eval workflows: eval questions and runs, costs,
conversations and the overview. Release rules stay in service.py.
"""

import asyncio
import random
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, timedelta

from chatbot.admin.costs import cost_usd, summarize
from chatbot.admin.evals import judge_agreement, run_metrics, simulate_results
from chatbot.admin.models import (
    ConversationDetail,
    ConversationSummary,
    CostSummary,
    EvalLabel,
    EvalQuestion,
    EvalQuestionCreate,
    EvalQuestionPatch,
    EvalResult,
    EvalRun,
    EvalRunDetail,
    Expected,
    Job,
    JobKind,
    JobProgress,
    JobStatus,
    LabelRequest,
    LlmCall,
    ModelPrice,
    Overview,
    QuestionStatus,
    ReleaseStatus,
    RunStatus,
    Stage,
    VersionStatus,
)
from chatbot.admin.service import AdminService, Conflict, NotFound

ANSWER_MODEL, JUDGE_MODEL, SYNTH_MODEL = "answer-medium", "judge-large", "synth-medium"
_LABEL = re.compile(r"^[a-z0-9][a-z0-9-]*#[a-z0-9][a-z0-9-]*$")
Work = Callable[[Job], Awaitable[None]]
SYNTH_TEMPLATES = ["How do I {}?", "What's the best way to handle {}?", "Can you explain {}?"]


class Invalid(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class AdminInsights:
    def __init__(self, admin: AdminService, personas: Mapping[str, frozenset[str]]) -> None:
        self.admin = admin
        self.repo = admin.repo
        self.personas = dict(personas)

    # --- eval questions -------------------------------------------------------------

    async def questions(self, status: str | None, source: str | None) -> list[EvalQuestion]:
        qs = await self.repo.list_questions()
        return sorted(
            (q for q in qs if status in (None, q.status) and source in (None, q.source)),
            key=lambda q: q.id,
        )

    async def question(self, question_id: str) -> EvalQuestion:
        q = await self.repo.get_question(question_id)
        if q is None:
            raise NotFound(f"no eval question {question_id}")
        return q

    async def create_question(self, body: EvalQuestionCreate, actor: str) -> EvalQuestion:
        await self._validate_expected(body.expected)
        now = self.admin.clock()
        q = EvalQuestion(
            id=await self.repo.next_question_id(),
            question=body.question,
            category=body.category,
            expected=body.expected,
            status=QuestionStatus.accepted,
            source="admin",
            created_by=actor,
            created_at=now,
            updated_at=now,
        )
        await self.repo.save_question(q)
        await self.admin._audit(actor, "eval.create", q.id)
        return q

    async def update_question(
        self, question_id: str, patch: EvalQuestionPatch, actor: str
    ) -> EvalQuestion:
        q = await self.question(question_id)
        if patch.expected is not None:
            await self._validate_expected(patch.expected)
            q.expected = patch.expected
        if patch.question is not None:
            q.question = patch.question
        if patch.category is not None:
            q.category = patch.category
        q.updated_at = self.admin.clock()
        await self.repo.save_question(q)
        await self.admin._audit(actor, "eval.update", q.id)
        return q

    async def review_question(self, question_id: str, accept: bool, actor: str) -> EvalQuestion:
        q = await self.question(question_id)
        if q.status != QuestionStatus.proposed:
            raise Conflict(f"{question_id} is {q.status}; only proposed questions can be reviewed")
        q.status = QuestionStatus.accepted if accept else QuestionStatus.rejected
        q.updated_at = self.admin.clock()
        await self.repo.save_question(q)
        await self.admin._audit(actor, "eval.accept" if accept else "eval.reject", q.id)
        return q

    async def _validate_expected(self, expected: Mapping[str, Expected]) -> None:
        """Personas must exist and labels must point at sections in the live or draft release."""
        errors = [
            f"unknown persona {p!r}" for p in expected if self.personas and p not in self.personas
        ]
        anchors = await self._known_anchors()
        for persona, exp in expected.items():
            for label in exp.required:
                if not _LABEL.match(label):
                    errors.append(f"{persona}: {label!r} is not a doc_id#anchor label")
                elif label not in anchors:
                    errors.append(
                        f"{persona}: {label} is not a section in the live or draft release"
                    )
        if errors:
            raise Invalid(errors)

    async def _known_anchors(self) -> set[str]:
        docs = {d.doc_id: d for d in await self.repo.list_documents()}
        out = set()
        for release in (await self.admin._live(), await self.admin.draft()):
            for doc_id, n in release.documents.items() if release else []:
                v = docs[doc_id].version(n) if doc_id in docs else None
                out |= {f"{doc_id}#{a}" for a in (v.anchors if v else [])}
        return out

    # --- synthetic questions (job) ------------------------------------------------------

    async def start_synthetic(self, doc_id: str, actor: str) -> Job:
        await self.admin._document(doc_id)  # 404 early
        job = await self._new_job("generate_synthetic_evals", doc_id=doc_id)
        await self.admin._audit(actor, "eval.generate_synthetic", doc_id, job=job.id)
        self.admin.jobs.start(lambda: self._synthesize(doc_id, job.id, actor))
        return job

    async def _synthesize(self, doc_id: str, job_id: str, actor: str) -> None:
        async def work(job: Job) -> None:
            doc = await self.admin._document(doc_id)
            version = next(
                (v for v in reversed(doc.versions) if v.status == VersionStatus.validated), None
            )
            if version is None:
                raise Conflict(f"{doc_id} has no validated version")
            await self._step(job, "generating", 50)
            sections = (version.anchors[1:] or version.anchors)[:3]
            now = self.admin.clock()
            picks = (sections * 3)[:3]  # three proposals, reusing sections if the doc is short
            for i, anchor in enumerate(picks):
                label = f"{doc_id}#{anchor}"
                missing = {
                    p: sorted(set(version.modules) - allowed)
                    for p, allowed in self.personas.items()
                }
                q = EvalQuestion(
                    id=await self.repo.next_question_id(),
                    question=SYNTH_TEMPLATES[i % len(SYNTH_TEMPLATES)].format(
                        anchor.replace("-", " ")
                    ),
                    category="single",
                    expected={
                        p: Expected(outcome="restricted", missing_modules=m)
                        if m
                        else Expected(outcome="answer", required=[label])
                        for p, m in missing.items()
                    },
                    status=QuestionStatus.proposed,
                    source="synthetic",
                    created_by=actor,
                    created_at=now,
                    updated_at=now,
                )
                await self.repo.save_question(q)
            rng = random.Random(job_id)
            await self._charge(
                "ingest",
                "synth",
                SYNTH_MODEL,
                [(rng.randint(3000, 5000), rng.randint(400, 800)) for _ in range(3)],
            )
            await self._step(job, "saving", 90)

        await self._run_job(job_id, work)

    # --- end-to-end eval runs (job) -------------------------------------------------------

    async def runs(self) -> list[EvalRun]:
        return sorted(await self.repo.list_runs(), key=lambda r: r.started_at, reverse=True)

    async def run(self, run_id: str) -> EvalRunDetail:
        r = await self.repo.get_run(run_id)
        if r is None:
            raise NotFound(f"no eval run {run_id}")
        results = await self.repo.list_results(run_id)
        return EvalRunDetail(
            **r.model_dump(), results=results, judge_agreement=judge_agreement(results)
        )

    async def start_run(self, actor: str) -> tuple[Job, str]:
        if any(r.status == RunStatus.running for r in await self.repo.list_runs()):
            raise Conflict("an eval run is already in progress")
        live = await self.admin._live()
        run = EvalRun(
            id=await self.repo.next_run_id(),
            status=RunStatus.running,
            started_by=actor,
            started_at=self.admin.clock(),
            release_id=live.id if live else None,
            answer_model=ANSWER_MODEL,
            judge_model=JUDGE_MODEL,
            prompt_version="answer@1",
        )
        job = await self._new_job("run_e2e_eval", run_id=run.id)
        run.job_id = job.id
        await self.repo.save_run(run)
        await self.admin._audit(actor, "eval.run", run.id, job=job.id)
        self.admin.jobs.start(lambda: self._run_e2e(run.id, job.id))
        return job, run.id

    async def _run_e2e(self, run_id: str, job_id: str) -> None:
        async def work(job: Job) -> None:
            accepted = [
                q for q in await self.repo.list_questions() if q.status == QuestionStatus.accepted
            ]
            await self._step(job, "generating answers", 30)
            results = simulate_results(run_id, accepted)
            await self._step(job, "judging", 70)
            rng = random.Random(run_id)
            cost = await self._charge(
                "eval",
                "generate",
                ANSWER_MODEL,
                [(rng.randint(2500, 4000), rng.randint(200, 400)) for _ in results],
            )
            cost += await self._charge(
                "eval",
                "judge",
                JUDGE_MODEL,
                [(rng.randint(1800, 2600), rng.randint(80, 160)) for _ in results],
            )
            await self._step(job, "scoring", 90)
            run = await self.repo.get_run(run_id)
            assert run is not None  # noqa: S101 - created before the job started
            run.status, run.finished_at = RunStatus.succeeded, self.admin.clock()
            run.questions, run.metrics, run.cost_usd = (
                len(accepted),
                run_metrics(results),
                round(cost, 8),
            )
            await self.repo.save_results(run_id, results)
            await self.repo.save_run(run)

        await self._run_job(job_id, work)
        job = await self.admin.job(job_id)
        if job.status == JobStatus.failed:
            run = await self.repo.get_run(run_id)
            if run:
                run.status, run.finished_at = RunStatus.failed, self.admin.clock()
                await self.repo.save_run(run)

    async def label_result(self, result_id: str, body: LabelRequest, actor: str) -> EvalResult:
        run_id = result_id.split(":", 1)[0]
        results = await self.repo.list_results(run_id)
        target = next((r for r in results if r.id == result_id), None)
        if target is None:
            raise NotFound(f"no eval result {result_id}")
        target.label = EvalLabel(
            faithful=body.faithful, correct=body.correct, labeller=actor, at=self.admin.clock()
        )
        await self.repo.save_results(run_id, results)
        await self.admin._audit(
            actor, "eval.label", result_id, faithful=body.faithful, correct=body.correct
        )
        return target

    # --- costs, conversations, overview ----------------------------------------------------

    async def costs(self, days: int) -> CostSummary:
        end = self.admin.clock().date()
        return summarize(await self.repo.list_llm_calls(), end - timedelta(days=days - 1), end)

    async def prices(self) -> list[ModelPrice]:
        return await self.repo.list_prices()

    async def conversations(
        self, tenant: str | None, sort: str, limit: int
    ) -> list[ConversationSummary]:
        summaries = await self._summaries()
        rows = [s for s in summaries.values() if tenant in (None, s.tenant)]
        if sort == "cost":
            rows.sort(key=lambda s: s.cost_usd, reverse=True)
        else:
            rows.sort(key=lambda s: s.last_active_at, reverse=True)
        return rows[:limit]

    async def conversation(self, conversation_id: str) -> ConversationDetail:
        summary = (await self._summaries()).get(conversation_id)
        if summary is None:
            raise NotFound(f"no conversation {conversation_id}")
        calls = [
            c for c in await self.repo.list_llm_calls() if c.conversation_id == conversation_id
        ]
        return ConversationDetail(
            **summary.model_dump(),
            messages=await self.repo.list_messages(conversation_id),
            llm_calls=sorted(calls, key=lambda c: c.created_at),
        )

    async def overview(self, stale_days: int = 90) -> Overview:
        releases = await self.admin.releases()
        docs = await self.admin.documents(stale_days)
        questions = await self.repo.list_questions()
        runs = await self.runs()
        now = self.admin.clock()
        month = summarize(
            await self.repo.list_llm_calls(), date(now.year, now.month, 1), now.date()
        )
        week_ago = now - timedelta(days=7)
        return Overview(
            live_release=next((r for r in releases if r.status == ReleaseStatus.live), None),
            draft_release=await self.admin.draft(),
            last_published=next(
                (r for r in releases if r.published_at and r.status != ReleaseStatus.draft), None
            ),
            documents=len(docs),
            stale_documents=sum(d.stale for d in docs),
            proposed_questions=sum(q.status == QuestionStatus.proposed for q in questions),
            accepted_questions=sum(q.status == QuestionStatus.accepted for q in questions),
            last_eval_run=runs[0] if runs else None,
            month_to_date_usd=month.total_usd,
            conversations_7d=sum(
                c.last_active_at >= week_ago for c in await self.repo.list_conversations()
            ),
        )

    async def _summaries(self) -> dict[str, ConversationSummary]:
        messages = defaultdict(list)
        for m in await self.repo.list_messages():
            messages[m.conversation_id].append(m)
        cost: dict[str, float] = defaultdict(float)
        for c in await self.repo.list_llm_calls():
            if c.conversation_id and c.bucket == "chat":
                cost[c.conversation_id] += c.cost_usd
        out = {}
        for conv in await self.repo.list_conversations():
            ms = messages[conv.conversation_id]
            replies = [m for m in ms if m.role == "assistant"]
            out[conv.conversation_id] = ConversationSummary(
                **conv.model_dump(),
                turns=sum(m.role == "user" for m in ms),
                last_outcome=replies[-1].outcome if replies else None,
                cost_usd=round(cost[conv.conversation_id], 8),
            )
        return out

    # --- job plumbing -------------------------------------------------------------------------

    async def _new_job(
        self, kind: JobKind, *, run_id: str | None = None, doc_id: str | None = None
    ) -> Job:
        job = Job(
            id=await self.repo.next_job_id(),
            kind=kind,
            status=JobStatus.queued,
            progress=JobProgress(stage="queued", pct=0),
            created_at=self.admin.clock(),
            run_id=run_id,
            doc_id=doc_id,
        )
        await self.repo.save_job(job)
        return job

    async def _step(self, job: Job, stage: str, pct: int) -> None:
        job.status, job.progress = JobStatus.running, JobProgress(stage=stage, pct=pct)
        await self.repo.save_job(job)
        await asyncio.sleep(self.admin.job_step_s)

    async def _run_job(self, job_id: str, work: Work) -> None:
        job = await self.admin.job(job_id)
        try:
            await work(job)
            job.status, job.progress = JobStatus.succeeded, JobProgress(stage="done", pct=100)
        except Exception as e:
            job.status, job.error = JobStatus.failed, f"{type(e).__name__}: {e}"
        job.finished_at = self.admin.clock()
        await self.repo.save_job(job)

    async def _charge(
        self, bucket: str, stage: Stage, model: str, tokens: list[tuple[int, int]]
    ) -> float:
        """Record internal (non-client) LLM spend; returns its total."""
        price = self.repo.price_for(model, self.admin.clock())
        if price is None:
            return 0.0
        now = self.admin.clock()
        calls = [
            LlmCall(
                id=self.repo.next_id("call"),
                trace_id=self.repo.next_id("t"),
                conversation_id=None,
                tenant=None,
                bucket=bucket,  # type: ignore[arg-type]
                stage=stage,
                model_id=model,
                provider=price.provider,
                input_tokens=i,
                output_tokens=o,
                price_id=price.price_id,
                cost_usd=cost_usd(i, o, 0, price),
                latency_ms=0.0,
                created_at=now,
            )
            for i, o in tokens
        ]
        await self.repo.add_llm_calls(calls)
        return sum(c.cost_usd for c in calls)
