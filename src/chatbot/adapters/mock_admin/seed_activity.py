"""Seed evals, prices and 60 days of chat/eval/ingest activity for the admin mock.

Runs after documents and releases are seeded (it reads their modules). Uses a
fixed RNG seed, so the dashboard looks the same on every start. Seeded text is
already redacted, as stored text always is.
"""

import random
import uuid
from datetime import datetime, timedelta

from chatbot.adapters.mock_admin.repository import InMemoryAdminRepository
from chatbot.admin.costs import cost_usd
from chatbot.admin.evals import run_metrics, simulate_results
from chatbot.admin.models import (
    Category,
    ConversationRecord,
    EvalLabel,
    EvalQuestion,
    EvalRun,
    Expected,
    LlmCall,
    Message,
    ModelPrice,
    Outcome,
    QuestionSource,
    QuestionStatus,
    RunStatus,
    Stage,
)
from chatbot.refusals import not_found_message

SEEDER = "seed@ops"
PLACEHOLDER_NOTE = "Placeholder estimate for the mock, not a real vendor price."

# Mirrors data/personas.yaml (seed data must not depend on the test persona set).
PERSONAS: dict[str, frozenset[str]] = {
    "sales_manager@acme": frozenset({"core", "contacts", "deals", "campaigns", "reports"}),
    "sales_rep@acme": frozenset({"core", "contacts", "deals"}),
    "sales_rep@globex": frozenset({"core", "contacts", "deals"}),
    "marketing_manager@globex": frozenset({"core", "contacts", "campaigns"}),
}
EVAL_PERSONAS = ("sales_manager@acme", "sales_rep@globex")
DISPLAY = {
    "core": "CRM basics",
    "contacts": "Contacts",
    "deals": "Deals",
    "campaigns": "Campaigns",
    "reports": "Reports",
}

PRICES = [
    ("mock", 1.0, 5.0, 0.1, "Made-up price for the mock responder."),
    ("rewrite-small", 0.25, 1.25, 0.03, PLACEHOLDER_NOTE),
    ("answer-medium", 3.0, 15.0, 0.3, PLACEHOLDER_NOTE),
    ("judge-large", 15.0, 75.0, 1.5, PLACEHOLDER_NOTE),
    ("synth-medium", 3.0, 15.0, 0.3, PLACEHOLDER_NOTE),
]

# (id, question, category, labels, outcome when there are no labels)
ACCEPTED: list[tuple[str, str, Category, list[str], Outcome]] = [
    (
        "q-0001",
        "When does a stage automation trigger?",
        "single",
        ["deals-stage-automation#triggers"],
        "answer",
    ),
    (
        "q-0002",
        "How do I set up a triggered email?",
        "single",
        ["campaigns-triggered-emails#setup"],
        "answer",
    ),
    (
        "q-0003",
        "How do I email contacts when a deal moves to a new stage?",
        "multi_hop",
        ["deals-stage-automation#actions", "campaigns-deal-triggers#connect-a-stage-to-a-campaign"],
        "answer",
    ),
    (
        "q-0004",
        "How do I import contacts from a spreadsheet?",
        "single",
        ["contacts-import#csv"],
        "answer",
    ),
    (
        "q-0005",
        "How do I build a dashboard?",
        "single",
        ["reports-dashboards#create-a-dashboard"],
        "answer",
    ),
    ("q-0006", "Where is search?", "single", ["core-navigation#search"], "answer"),
    (
        "q-0007",
        "How do I create a new pipeline?",
        "single",
        ["deals-pipeline-setup#create-a-pipeline"],
        "answer",
    ),
    (
        "q-0008",
        "Can I rename a deal stage?",
        "single",
        ["deals-pipeline-setup#edit-stages"],
        "answer",
    ),
    (
        "q-0009",
        "What forecast categories are there?",
        "single",
        ["deals-forecasting#forecast-categories"],
        "answer",
    ),
    (
        "q-0010",
        "Is there a daily limit on triggered emails?",
        "single",
        ["campaigns-triggered-emails#send-limits"],
        "answer",
    ),
    (
        "q-0011",
        "How do I exclude customers from an audience?",
        "single",
        ["campaigns-audiences#exclusions"],
        "answer",
    ),
    (
        "q-0012",
        "How do I map CSV columns to contact fields?",
        "single",
        ["contacts-import#mapping-fields"],
        "answer",
    ),
    (
        "q-0013",
        "Two contacts are the same person. How do I merge them?",
        "single",
        ["contacts-merge-duplicates#merge-two-contacts"],
        "answer",
    ),
    (
        "q-0014",
        "How do I share a dashboard?",
        "single",
        ["reports-dashboards#share-a-dashboard"],
        "answer",
    ),
    (
        "q-0015",
        "How do I turn off email notifications?",
        "single",
        ["core-notifications#email-notifications"],
        "answer",
    ),
    (
        "q-0016",
        "How do I test an automation before switching it on?",
        "single",
        ["deals-stage-automation#testing-an-automation"],
        "answer",
    ),
    ("q-0017", "What's the weather in Paris?", "out_of_scope", [], "out_of_scope"),
    ("q-0018", "How do I export the whole CRM to SAP?", "unanswerable", [], "not_found"),
    (
        "q-0019",
        "How do I schedule a report export?",
        "single",
        ["reports-scheduled-exports#schedule-an-export"],
        "answer",
    ),
    (
        "q-0020",
        "How do deal forecasts show up in reports?",
        "multi_hop",
        ["deals-forecasting#forecast-reports", "reports-dashboards#create-a-dashboard"],
        "answer",
    ),
]
PROPOSED: list[tuple[str, str, list[str]]] = [
    (
        "q-0021",
        "What's the quickest way to build an audience of recent buyers?",
        ["campaigns-audiences#build-an-audience"],
    ),
    ("q-0022", "Can I mute in-app alerts?", ["core-notifications#in-app-notifications"]),
    ("q-0023", "How do I reorder pipeline stages?", ["deals-pipeline-setup#edit-stages"]),
    ("q-0024", "Can I add a chart to a dashboard?", ["reports-dashboards#create-a-dashboard"]),
    ("q-0025", "How do I favourite a record?", ["core-navigation#favourites"]),
]

# (question as stored, i.e. already redacted; module it needs, or None if unanswerable)
QUESTION_BANK: list[tuple[str, str | None]] = [
    ("how do I move a deal to the next stage", "deals"),
    ("can I automate stage changes when a quote is signed", "deals"),
    ("how do I add a new pipeline for renewals", "deals"),
    ("how do I send an email when a deal is won", "campaigns"),
    ("why didn't [email] get the renewal reminder", "campaigns"),
    ("how do I build an audience of trial users", "campaigns"),
    ("import contacts from a csv", "contacts"),
    ("how do I merge duplicate contacts", "contacts"),
    ("customer on [phone] appears twice, how do I fix it", "contacts"),
    ("how do I share a dashboard with my team", "reports"),
    ("schedule a weekly pipeline export", "reports"),
    ("where do I change notification settings", "core"),
    ("how do I search across all records", "core"),
    ("can the CRM book flights", None),
    ("what's our refund policy for customers", None),
]
ANSWERS = {
    "deals": (
        "**Deals:** stage changes can trigger automations.\n\n"
        "1. Open **Deals → Pipeline settings**.\n2. Choose the stage and select **Add trigger**."
    ),
    "campaigns": (
        "**Campaigns:** triggered emails send when a condition is met.\n\n"
        "1. Go to **Campaigns → Triggered emails**.\n2. Choose the trigger and audience."
    ),
    "contacts": "**Contacts:** bulk-import or merge people from **Contacts → Import**.",
    "reports": "**Reports:** open **Reports → Dashboards** to create, share or schedule.",
    "core": "Use the search bar at the top, or open **Settings → Notifications**.",
}


def _expected(
    labels: list[str], outcome: Outcome, doc_modules: dict[str, list[str]]
) -> dict[str, Expected]:
    if not labels:
        return {p: Expected(outcome=outcome) for p in EVAL_PERSONAS}
    needed = {m for lbl in labels for m in doc_modules[lbl.split("#")[0]]}
    out = {}
    for p in EVAL_PERSONAS:
        missing = sorted(needed - PERSONAS[p])
        out[p] = (
            Expected(outcome="restricted", missing_modules=missing)
            if missing
            else Expected(outcome="answer", required=labels)
        )
    return out


def _restricted_text(modules: list[str]) -> str:
    names = [DISPLAY[m] for m in sorted(modules)]
    joined = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    return (
        f"This question involves {joined}, which isn't included in your current access. "
        "If you need it, ask your CRM administrator about access."
    )


def seed_activity(repo: InMemoryAdminRepository, now: datetime) -> None:
    rng = random.Random(42)
    repo.prices = [
        ModelPrice(
            price_id=f"price-{model}",
            model_id=model,
            provider="placeholder",
            input_per_mtok=i,
            output_per_mtok=o,
            cached_input_per_mtok=c,
            valid_from=now - timedelta(days=400),
            note=note,
        )
        for model, i, o, c, note in PRICES
    ]
    price = {p.model_id: p for p in repo.prices}

    def add_call(
        at: datetime,
        bucket: str,
        stage: Stage,
        model: str,
        inp: int,
        out: int,
        *,
        cached: int = 0,
        tenant: str | None = None,
        conv: str | None = None,
        trace: str | None = None,
    ) -> LlmCall:
        call = LlmCall(
            id=repo.next_id("call"),
            trace_id=trace or repo.next_id("t"),
            conversation_id=conv,
            tenant=tenant,
            bucket=bucket,  # type: ignore[arg-type]
            stage=stage,
            model_id=model,
            provider="placeholder",
            input_tokens=inp,
            output_tokens=out,
            cached_input_tokens=cached,
            price_id=price[model].price_id,
            cost_usd=cost_usd(inp, out, cached, price[model]),
            latency_ms=round(rng.uniform(300, 2500), 1),
            created_at=at,
        )
        repo.llm_calls.append(call)
        return call

    # --- eval questions (expected outcomes follow the live release's modules) ---------
    live = repo.releases["r3"].documents
    doc_modules = {d: repo.documents[d].version(v).modules for d, v in live.items()}  # type: ignore[union-attr]
    created = now - timedelta(days=45)

    def question(
        qid: str,
        text: str,
        category: Category,
        labels: list[str],
        outcome: Outcome,
        status: QuestionStatus,
        source: QuestionSource,
        at: datetime,
    ) -> EvalQuestion:
        return EvalQuestion(
            id=qid,
            question=text,
            category=category,
            expected=_expected(labels, outcome, doc_modules),
            status=status,
            source=source,
            created_by=SEEDER,
            created_at=at,
            updated_at=at,
        )

    for qid, text, category, labels, outcome in ACCEPTED:
        repo.questions[qid] = question(
            qid, text, category, labels, outcome, QuestionStatus.accepted, "file", created
        )
    for qid, text, labels in PROPOSED:
        repo.questions[qid] = question(
            qid,
            text,
            "single",
            labels,
            "answer",
            QuestionStatus.proposed,
            "synthetic",
            now - timedelta(days=2),
        )

    # --- two past end-to-end runs, the second partly labelled ---------------------------
    accepted = [q for q in repo.questions.values() if q.status == QuestionStatus.accepted]
    for run_id, days, release in (("e-1", 14, "r2"), ("e-2", 3, "r3")):
        at = now - timedelta(days=days)
        results = simulate_results(run_id, accepted)
        run_cost = 0.0
        for _ in results:
            run_cost += add_call(
                at,
                "eval",
                "generate",
                "answer-medium",
                rng.randint(2500, 4000),
                rng.randint(200, 400),
            ).cost_usd
            run_cost += add_call(
                at, "eval", "judge", "judge-large", rng.randint(1800, 2600), rng.randint(80, 160)
            ).cost_usd
        if run_id == "e-2":
            for i, r in enumerate([r for r in results if r.actual_outcome == "answer"][:8]):
                r.label = EvalLabel(
                    faithful=r.judge_faithful if i % 4 else not r.judge_faithful,
                    correct=r.judge_correct,
                    labeller="editor@ops",
                    at=at + timedelta(hours=5),
                )
        repo.runs[run_id] = EvalRun(
            id=run_id,
            status=RunStatus.succeeded,
            started_by=SEEDER,
            started_at=at,
            finished_at=at + timedelta(minutes=12),
            release_id=release,
            answer_model="answer-medium",
            judge_model="judge-large",
            prompt_version="answer@1",
            questions=len(accepted),
            metrics=run_metrics(results),
            cost_usd=round(run_cost, 6),
        )
        repo.results[run_id] = results

    # --- synthetic question generation (internal "ingest" spend) ------------------------
    for days in (50, 35, 20, 2):
        for _ in range(3):
            add_call(
                now - timedelta(days=days),
                "ingest",
                "synth",
                "synth-medium",
                rng.randint(3000, 5000),
                rng.randint(400, 800),
            )

    # --- 60 days of chat ------------------------------------------------------------------
    roles = {"acme": ["sales_manager", "sales_rep"], "globex": ["sales_rep", "marketing_manager"]}
    for days in range(59, -1, -1):
        day = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
        for tenant in ("acme", "globex"):
            for _ in range(rng.randint(2, 6)):
                role = rng.choice(roles[tenant])
                allowed = PERSONAS[f"{role}@{tenant}"]
                start = day + timedelta(hours=rng.uniform(8, 18))
                if start > now:
                    continue
                conv_id = str(uuid.UUID(int=rng.getrandbits(128), version=4))
                turns = rng.choice([1, 1, 1, 2, 2, 3])
                at = start
                for turn in range(turns):
                    text, module = rng.choice(QUESTION_BANK)
                    trace = repo.next_id("t")
                    if module is None:
                        turn_outcome, answer = "refusal:not_found", not_found_message()
                    elif module not in allowed:
                        turn_outcome, answer = "refusal:restricted", _restricted_text([module])
                    else:
                        turn_outcome, answer = "answer", ANSWERS[module]
                        if turn:
                            add_call(
                                at,
                                "chat",
                                "rewrite",
                                "rewrite-small",
                                rng.randint(300, 600),
                                rng.randint(40, 90),
                                tenant=tenant,
                                conv=conv_id,
                                trace=trace,
                            )
                        add_call(
                            at,
                            "chat",
                            "generate",
                            "answer-medium",
                            rng.randint(2500, 4500),
                            rng.randint(150, 450),
                            cached=rng.randint(0, 2000) if turn else 0,
                            tenant=tenant,
                            conv=conv_id,
                            trace=trace,
                        )
                    repo.messages += [
                        Message(
                            id=repo.next_id("msg"),
                            conversation_id=conv_id,
                            trace_id=trace,
                            role="user",
                            content=text,
                            created_at=at,
                        ),
                        Message(
                            id=repo.next_id("msg"),
                            conversation_id=conv_id,
                            trace_id=trace,
                            role="assistant",
                            content=answer,
                            outcome=turn_outcome,
                            created_at=at + timedelta(seconds=4),
                        ),
                    ]
                    at += timedelta(minutes=rng.uniform(1, 6))
                repo.conversations[conv_id] = ConversationRecord(
                    conversation_id=conv_id,
                    sub=f"user-{tenant}-{rng.randint(1, 12):02d}",
                    tenant=tenant,
                    role=role,
                    created_at=start,
                    last_active_at=at,
                )
