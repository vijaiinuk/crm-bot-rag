"""The publish gate (S2.4.1): every new index version is checked before it can go live.

    1. orphaned labels   a golden doc_id#anchor matching no chunk          zero tolerance
    2. permission suite  any leak or vacuous result, full matrix           zero tolerance
    3. recall regression reranked overall metrics vs the live version      config/gate.yaml
    4. module widening   a doc dropping a module the live version required needs confirming

Widening is not a leak (a doc retagged [core] is correctly shown to everyone with core);
the danger is the new tag itself, so a person has to confirm it (architecture §4).
"""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, ConfigDict, Field

from chatbot.evals import permissions
from chatbot.evals.golden import GoldenQuestion
from chatbot.evals.labels import OrphanLabels
from chatbot.evals.metrics import Summary
from chatbot.evals.runner import VersionEval, evaluate_version
from chatbot.ports.reranker import Reranker
from chatbot.ports.retriever import Retriever

Metric = Literal[
    "complete@5", "recall@5", "mrr", "complete@3", "recall@3", "complete@1", "recall@1"
]


class RegressionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metrics: list[Metric] = Field(min_length=1)
    tolerance: float = Field(ge=0, le=0.5)


class GateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    regression: RegressionConfig


def load_gate_config(path: Path) -> GateConfig:
    return GateConfig.model_validate(yaml.safe_load(path.read_text()))


def metric_value(s: Summary, metric: Metric) -> float:
    if metric == "mrr":
        return s.mrr
    name, k = metric.split("@")
    return (s.complete if name == "complete" else s.recall)[int(k)]


@dataclass(frozen=True, slots=True)
class Regression:
    metric: str
    live: float
    new: float

    @property
    def drop(self) -> float:
        return self.live - self.new


def regressions(new: Summary, live: Summary, config: RegressionConfig) -> list[Regression]:
    """Metrics that fell by more than the tolerance. Improvements never block."""
    out = []
    for m in config.metrics:
        r = Regression(m, metric_value(live, m), metric_value(new, m))
        if r.drop > config.tolerance + 1e-9:
            out.append(r)
    return out


@dataclass(frozen=True, slots=True)
class Widening:
    doc_id: str
    live: tuple[str, ...]
    new: tuple[str, ...]
    dropped: tuple[str, ...]  # modules the live version required that the new one doesn't


def widenings(
    live: Mapping[str, tuple[str, ...]], new: Mapping[str, tuple[str, ...]]
) -> tuple[list[Widening], list[str]]:
    """(docs whose access widened, docs that are new). A chunk needs ALL its modules, so
    dropping any module widens access, even if another is added; adding only narrows."""
    widened, added = [], []
    for doc_id in sorted(new):
        if doc_id not in live:
            added.append(doc_id)
            continue
        dropped = tuple(sorted(set(live[doc_id]) - set(new[doc_id])))
        if dropped:
            widened.append(Widening(doc_id, live[doc_id], new[doc_id], dropped))
    return widened, added


@dataclass
class GateReport:
    version: int
    live_version: int | None
    passed: bool = False
    failures: list[str] = field(default_factory=list)  # one line per failed check
    orphans: list[str] = field(default_factory=list)
    permissions: dict[str, Any] = field(default_factory=dict)
    regression: dict[str, Any] = field(default_factory=dict)
    widening: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


async def run_gate(
    pool: AsyncConnectionPool,
    version: int,
    live_version: int | None,
    *,
    retriever: Retriever,
    reranker: Reranker,
    golden: Sequence[GoldenQuestion],
    personas: Mapping[str, frozenset[str]],
    entitlements: Sequence[permissions.Entitlement],
    threshold: float,
    config: GateConfig,
    confirm_widening: bool = False,
    permission_queries: Sequence[permissions.Query] | None = None,  # None: the full set
) -> GateReport:
    report = GateReport(version, live_version)
    common: dict[str, Any] = {
        "retriever": retriever,
        "reranker": reranker,
        "golden": golden,
        "personas": personas,
        "threshold": threshold,
    }

    # 1. Orphaned labels: evaluate_version checks them before searching anything.
    try:
        new = await evaluate_version(
            pool,
            version,
            entitlements=entitlements,
            permission_queries=permission_queries,
            **common,
        )
    except OrphanLabels as e:
        report.orphans = e.labels
        report.failures.append(f"orphaned eval labels: {', '.join(e.labels)}")
        return report  # nothing else can be measured against missing labels

    # 2. Permission suite: zero tolerance.
    perm = new.permissions
    if perm is None:
        raise RuntimeError("permission suite did not run")
    report.permissions = {
        "passed": perm.passed,
        "searches": perm.searches,
        "checked": perm.checked,
        "violations": [asdict(v) for v in perm.violations[:200]],
        "vacuous": [asdict(v) for v in perm.vacuous[:200]],
    }
    if perm.violations:
        report.failures.append(f"permission leaks: {len(perm.violations)}")
    if perm.vacuous:
        report.failures.append(f"vacuous permission results: {len(perm.vacuous)}")

    # 3. Recall regression vs live; 4. module widening vs live.
    live: VersionEval | None = None
    if live_version is not None:
        live = await evaluate_version(pool, live_version, **common)
    _regression(report, new, live, config.regression)
    _widening(report, new, live, confirm_widening)

    report.passed = not report.failures
    return report


def _regression(
    report: GateReport, new: VersionEval, live: VersionEval | None, config: RegressionConfig
) -> None:
    new_overall = new.run.summaries["rerank"]["overall"]
    values = {m: metric_value(new_overall, m) for m in config.metrics}
    if live is None:
        report.regression = {"note": "no live version to compare with", "new": values}
        return
    live_overall = live.run.summaries["rerank"]["overall"]
    found = regressions(new_overall, live_overall, config)
    report.regression = {
        "tolerance": config.tolerance,
        "new": values,
        "live": {m: metric_value(live_overall, m) for m in config.metrics},
        "regressions": [asdict(r) | {"drop": r.drop} for r in found],
    }
    for r in found:
        report.failures.append(
            f"{r.metric} regressed {r.live:.3f} -> {r.new:.3f} (tolerance {config.tolerance})"
        )


def _widening(
    report: GateReport, new: VersionEval, live: VersionEval | None, confirmed: bool
) -> None:
    widened, added = widenings(live.doc_modules if live else {}, new.doc_modules)
    if live is None:
        added = []  # the very first version: everything is "new", nothing to compare
    report.widening = {
        "widened": [asdict(w) for w in widened],
        "new_docs": added,
        "confirmed": confirmed and bool(widened),
    }
    if widened and not confirmed:
        docs = ", ".join(f"{w.doc_id} (drops {', '.join(w.dropped)})" for w in widened)
        report.failures.append(
            f"module access widened, needs confirmation (CONFIRM_WIDENING=1): {docs}"
        )
