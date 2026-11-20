"""Retrieval eval run (S2.3.1): every golden (question, persona) pair through hybrid search
and the reranker, scored at both stages. Design: docs/backlog.md, "S2.3.1 design".

No LLM. Labels are checked against the evaluated index first; an orphan aborts the run.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from chatbot.evals.golden import GoldenError, GoldenQuestion
from chatbot.evals.labels import check_labels
from chatbot.evals.metrics import (
    DEPTH,
    KS,
    GateCounts,
    PairResult,
    Summary,
    gate_counts,
    summarize,
)
from chatbot.ports.reranker import Reranker
from chatbot.ports.retriever import Candidate, Retriever

STAGES = ("rerank", "hybrid")  # report order: what the generator would see first


@dataclass
class PairRecord:
    """Everything about one pair, for the JSON report."""

    question_id: str
    persona: str
    category: str
    outcome: str
    required: list[str]
    hybrid: list[str]  # chunk ids, best first
    reranked: list[str]
    rerank_scores: list[float]


@dataclass
class RunResult:
    index_version: int
    threshold: float
    summaries: dict[str, dict[str, Summary]]  # stage -> category -> summary
    gate: dict[str, GateCounts]
    pairs: list[PairRecord] = field(default_factory=list)


def load_golden(paths: Sequence[Path]) -> list[GoldenQuestion]:
    questions: list[GoldenQuestion] = []
    for path in paths:
        questions += [GoldenQuestion.model_validate(q) for q in yaml.safe_load(path.read_text())]
    ids = [q.id for q in questions]
    if dupes := sorted({i for i in ids if ids.count(i) > 1}):
        raise GoldenError(f"duplicate question ids across golden files: {dupes}")
    if not questions:
        raise GoldenError("no golden questions found")
    return questions


async def run_retrieval_eval(
    golden: Sequence[GoldenQuestion],
    personas: Mapping[str, frozenset[str]],
    retriever: Retriever,
    reranker: Reranker,
    labels_of: Mapping[str, frozenset[str]],  # chunk_id -> labels it satisfies (this version)
    *,
    index_version: int,
    threshold: float,
    pool: int = DEPTH,
    ks: Sequence[int] = KS,
) -> RunResult:
    unknown = sorted({p for q in golden for p in q.expected if p not in personas})
    if unknown:
        raise GoldenError(f"golden set uses personas not in personas.yaml: {unknown}")
    check_labels(
        (label for q in golden for e in q.expected.values() for label in e.required), labels_of
    )

    def ranking(candidates: Sequence[Candidate]) -> tuple[frozenset[str], ...]:
        return tuple(labels_of[c.chunk_id] for c in candidates)

    results: dict[str, list[PairResult]] = {stage: [] for stage in STAGES}
    outcomes: list[tuple[str, float | None]] = []
    records: list[PairRecord] = []
    for q in golden:
        for persona, e in q.expected.items():
            hybrid = await retriever.search(
                q.question, personas[persona], pool, index_version=index_version
            )
            reranked = await reranker.rerank(q.question, hybrid, pool)
            outcomes.append((e.outcome, reranked[0].rerank_score if reranked else None))
            if e.outcome == "answer":
                required = tuple(e.required)
                for stage, cands in (("hybrid", hybrid), ("rerank", reranked)):
                    results[stage].append(
                        PairResult(q.id, persona, q.category, required, ranking(cands))
                    )
            records.append(
                PairRecord(
                    question_id=q.id,
                    persona=persona,
                    category=q.category,
                    outcome=e.outcome,
                    required=list(e.required),
                    hybrid=[c.chunk_id for c in hybrid],
                    reranked=[c.chunk_id for c in reranked],
                    rerank_scores=[round(c.rerank_score or 0.0, 4) for c in reranked],
                )
            )
    return RunResult(
        index_version=index_version,
        threshold=threshold,
        summaries={stage: summarize(rs, ks) for stage, rs in results.items()},
        gate=gate_counts(outcomes, threshold),
        pairs=records,
    )


# --- the readable report --------------------------------------------------------------------

_STAGE_TITLE = {"rerank": "Hybrid + rerank", "hybrid": "Hybrid only"}
_GROUP_TITLE = {
    "answer": ("answer", "kept (should be ~100%)"),
    "nothing": ("not found / out of scope", "refused (should be ~100%)"),
    "restricted": ("restricted", "refused (rest: partial access, S3.1.3b)"),
}


def render_markdown(run: RunResult, header: Mapping[str, Any]) -> str:
    lines = [f"# Retrieval eval: index v{run.index_version}", ""]
    lines += [f"- {k}: `{v}`" for k, v in header.items()]
    for stage in STAGES:
        summaries = run.summaries[stage]
        ks = list(next(iter(summaries.values())).recall)
        lines += ["", f"## {_STAGE_TITLE[stage]}", ""]
        cols = [f"recall@{k}" for k in ks] + [f"complete@{k}" for k in ks] + ["MRR"]
        lines += [
            "| category | n | " + " | ".join(cols) + " |",
            "|---|---:|" + "---:|" * len(cols),
        ]
        for cat, s in summaries.items():
            cells = [f"{s.recall[k]:.2f}" for k in ks] + [f"{s.complete[k]:.2f}" for k in ks]
            name = f"**{cat}**" if cat == "overall" else cat
            lines.append(f"| {name} | {s.n} | " + " | ".join([*cells, f"{s.mrr:.2f}"]) + " |")
    lines += [
        "",
        f"## Threshold {run.threshold} on the top rerank score",
        "",
        "| expected | n | above threshold | |",
        "|---|---:|---:|---|",
    ]
    for group, g in run.gate.items():
        title, meaning = _GROUP_TITLE[group]
        refused = g.n - g.above
        shown = g.above if group == "answer" else refused
        pct = shown / g.n if g.n else 0.0
        lines.append(f"| {title} | {g.n} | {g.above} | {pct:.1%} {meaning} |")
    return "\n".join(lines) + "\n"
