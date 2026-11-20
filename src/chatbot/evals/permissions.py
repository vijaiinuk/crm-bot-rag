"""The permission suite (S2.3.2): zero tolerance. Design: docs/backlog.md, "S2.3.2 design".

For every (query, entitlement set): every candidate, at every stage, must have modules
that are a subset of the allowed set (rules 2 and 5). And the result must not be
vacuous: a suite that passes because retrieval returned nothing proves nothing, so a
visible chunk queried with its own text must be found, and a set that can see anything
must get results.

Shared by pytest (corpus index, fake embedder), `make eval` (live index) and the
S2.4.1 publish gate (the new version, before promotion).
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from chatbot.ports.reranker import Reranker
from chatbot.ports.retriever import Candidate, Retriever

# Names that look like modules but are not: they must never widen access.
BOGUS_MODULES = ("Deals", "deals ", "admin", "*")


@dataclass(frozen=True, slots=True)
class Query:
    id: str
    text: str
    expect_chunk: str | None = None  # self-retrieval: this chunk must be found when visible


@dataclass(frozen=True, slots=True)
class Entitlement:
    name: str
    allowed: frozenset[str]


@dataclass(frozen=True, slots=True)
class Violation:
    """A leak: a candidate with a module outside the allowed set."""

    query_id: str
    entitlement: str
    stage: str  # "hybrid" | "rerank"
    chunk_id: str
    modules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Vacuous:
    """Nothing came back (or the expected chunk did not) although it was visible."""

    query_id: str
    entitlement: str
    reason: str


@dataclass
class PermissionReport:
    searches: int = 0
    checked: int = 0  # candidates checked, all stages
    violations: list[Violation] = field(default_factory=list)
    vacuous: list[Vacuous] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.violations and not self.vacuous


def entitlement_matrix(
    personas: Mapping[str, frozenset[str]], modules: Sequence[str]
) -> list[Entitlement]:
    """Every persona, then: nothing, core only, each module alone, everything, and sets
    with bogus names. Identical allowed sets are kept once (the first name wins)."""
    out: list[Entitlement] = []
    seen: set[frozenset[str]] = set()

    def add(name: str, allowed: frozenset[str]) -> None:
        if allowed not in seen:
            seen.add(allowed)
            out.append(Entitlement(name, allowed))

    for name, allowed in personas.items():
        add(name, frozenset(allowed))
    add("nothing", frozenset())
    for m in modules:
        add(f"only:{m}", frozenset({m}))
    add("all", frozenset(modules))
    add("bogus-only", frozenset(BOGUS_MODULES))
    add("core+bogus", frozenset({"core", *BOGUS_MODULES}))
    return out


def self_retrieval_queries(chunks: Sequence[tuple[str, str]]) -> list[Query]:
    """(chunk_id, embed_text) -> one query per chunk, asking for exactly that chunk."""
    return [Query(f"self:{chunk_id}", text, expect_chunk=chunk_id) for chunk_id, text in chunks]


async def run_permission_suite(
    retriever: Retriever,
    reranker: Reranker | None,
    *,
    index_version: int,
    entitlements: Sequence[Entitlement],
    queries: Sequence[Query],
    chunk_modules: Mapping[str, tuple[str, ...]],  # every chunk in the version -> its modules
    k: int = 20,
    concurrency: int = 4,  # searches in flight; keep <= the pool's connections
) -> PermissionReport:
    gate = asyncio.Semaphore(concurrency)

    async def stages(q: Query, e: Entitlement) -> list[tuple[str, list[Candidate]]]:
        async with gate:
            hybrid = await retriever.search(q.text, e.allowed, k, index_version=index_version)
            out = [("hybrid", hybrid)]
            if reranker is not None:  # even on empty input: a reranker must not add chunks
                out.append(("rerank", await reranker.rerank(q.text, hybrid, k)))
            return out

    cases = [(q, e) for e in entitlements for q in queries]
    results = await asyncio.gather(*(stages(q, e) for q, e in cases))

    report = PermissionReport(searches=len(cases))
    sees_anything = {
        e.name: any(set(mods) <= e.allowed for mods in chunk_modules.values()) for e in entitlements
    }
    for (q, e), per_stage in zip(cases, results, strict=True):
        for stage, candidates in per_stage:
            for c in candidates:
                report.checked += 1
                # Judge by the index's record, not the candidate's own claim; a chunk the
                # index doesn't know is a violation too (fail closed).
                modules = chunk_modules.get(c.chunk_id)
                if modules is None or not set(modules) <= e.allowed:
                    report.violations.append(
                        Violation(q.id, e.name, stage, c.chunk_id, modules or ("<unknown>",))
                    )
        hybrid_ids = {c.chunk_id for c in per_stage[0][1]}
        expect = q.expect_chunk
        if expect is not None and set(chunk_modules[expect]) <= e.allowed:
            if expect not in hybrid_ids:
                report.vacuous.append(
                    Vacuous(q.id, e.name, f"{expect} is visible but its own text did not find it")
                )
        elif sees_anything[e.name] and not hybrid_ids:
            report.vacuous.append(
                Vacuous(q.id, e.name, "visible content exists but nothing came back")
            )
    return report


def render_markdown(report: PermissionReport, *, entitlements: int, queries: int) -> str:
    verdict = "PASS" if report.passed else "**FAIL**"
    lines = [
        "## Permission suite (zero tolerance)",
        "",
        f"{verdict}: {report.searches} searches ({entitlements} entitlement sets x {queries} "
        f"queries), {report.checked} candidates checked, {len(report.violations)} leaks, "
        f"{len(report.vacuous)} vacuous results.",
    ]
    if report.violations:
        lines += ["", "| query | entitlement | stage | chunk | modules |", "|---|---|---|---|---|"]
        for v in report.violations[:50]:
            mods = ", ".join(v.modules)
            lines.append(f"| {v.query_id} | {v.entitlement} | {v.stage} | {v.chunk_id} | {mods} |")
    if report.vacuous:
        lines += ["", "| query | entitlement | why |", "|---|---|---|"]
        lines += [f"| {v.query_id} | {v.entitlement} | {v.reason} |" for v in report.vacuous[:50]]
    return "\n".join(lines) + "\n"
