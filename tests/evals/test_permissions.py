"""S2.3.2: the permission suite itself. Before trusting a zero, prove the suite catches
leaks AND catches a retriever that passes only by returning nothing."""

from collections.abc import Sequence
from dataclasses import replace

from chatbot.evals.permissions import (
    BOGUS_MODULES,
    Entitlement,
    PermissionReport,
    Query,
    entitlement_matrix,
    run_permission_suite,
    self_retrieval_queries,
)
from chatbot.ports.reranker import Reranker
from chatbot.ports.retriever import Candidate

# A tiny index: chunk -> modules.
CHUNKS: dict[str, tuple[str, ...]] = {
    "core-x#a:0": ("core",),
    "deals-x#a:0": ("deals",),
    "deals-x#b:0": ("deals", "campaigns"),
}
REP = Entitlement("rep@acme", frozenset({"core", "deals"}))
NOBODY = Entitlement("nothing", frozenset())


def cand(chunk_id: str) -> Candidate:
    doc, rest = chunk_id.split("#")
    return Candidate(
        chunk_id, doc, rest.split(":")[0], "B", "C", chunk_id, CHUNKS[chunk_id], 1, 1, None, 0.1
    )


class FilteringRetriever:
    """Correct: filters inside the search, before ranking."""

    def __init__(self, post_filter_bug: bool = False, drop: str | None = None) -> None:
        self.post_filter_bug = post_filter_bug
        self.drop = drop

    async def live_version(self) -> int:
        return 1

    async def search(
        self, query: str, allowed_modules: frozenset[str], k: int, *, index_version: int
    ) -> list[Candidate]:
        ranked = sorted(CHUNKS, key=lambda c: c != query)  # the chunk named by the query first
        if not self.post_filter_bug:
            ranked = [c for c in ranked if set(CHUNKS[c]) <= allowed_modules]
        else:  # the classic bug: rank everything, keep the top k, "filter" only the first
            ranked = ranked[:k]
        return [cand(c) for c in ranked if c != self.drop][:k]


class EmptyRetriever(FilteringRetriever):
    async def search(
        self, query: str, allowed_modules: frozenset[str], k: int, *, index_version: int
    ) -> list[Candidate]:
        return []


class InjectingReranker:
    key = "bad@1"

    async def rerank(self, query: str, candidates: Sequence[Candidate], k: int) -> list[Candidate]:
        return [replace(cand("deals-x#b:0"), rerank_score=0.99), *candidates][:k]


def self_queries() -> list[Query]:
    return self_retrieval_queries([(c, c) for c in CHUNKS])  # query text = chunk id, see above


async def suite(
    retriever: FilteringRetriever,
    reranker: Reranker | None = None,
    entitlements: Sequence[Entitlement] = (REP, NOBODY),
) -> PermissionReport:
    return await run_permission_suite(
        retriever,
        reranker,
        index_version=1,
        entitlements=list(entitlements),
        queries=self_queries(),
        chunk_modules=CHUNKS,
    )


# --- the suite catches what it must ---------------------------------------------------------


async def test_a_correct_retriever_passes_with_every_candidate_checked() -> None:
    report = await suite(FilteringRetriever())
    assert report.passed and report.violations == [] and report.vacuous == []
    assert report.searches == 3 * 2  # 3 queries x 2 entitlement sets
    assert report.checked == 3 * 2  # rep sees 2 chunks per query; nothing sees none


async def test_a_post_filtering_retriever_is_caught_as_a_leak() -> None:
    report = await suite(FilteringRetriever(post_filter_bug=True))
    assert not report.passed
    leak = next(v for v in report.violations if v.entitlement == "rep@acme")
    assert (leak.chunk_id, leak.modules, leak.stage) == (
        "deals-x#b:0",
        ("deals", "campaigns"),
        "hybrid",
    )
    assert {v.entitlement for v in report.violations} == {"rep@acme", "nothing"}


async def test_a_retriever_that_returns_nothing_is_caught_as_vacuous() -> None:
    """Zero leaks, but only because nothing came back: that must fail too."""
    report = await suite(EmptyRetriever())
    assert report.violations == [] and not report.passed
    assert {(v.query_id, v.entitlement) for v in report.vacuous} >= {
        ("self:core-x#a:0", "rep@acme"),
        ("self:deals-x#a:0", "rep@acme"),
    }
    assert all(v.entitlement != "nothing" for v in report.vacuous), (
        "nothing visible: empty is right"
    )


async def test_a_visible_chunk_missing_from_its_own_query_is_vacuous() -> None:
    report = await suite(FilteringRetriever(drop="deals-x#a:0"))
    assert [(v.query_id, v.entitlement) for v in report.vacuous] == [
        ("self:deals-x#a:0", "rep@acme")
    ]
    assert "deals-x#a:0" in report.vacuous[0].reason


async def test_an_invisible_chunk_need_not_be_found() -> None:
    """deals-x#b:0 needs campaigns, which the rep lacks: not finding it is correct."""
    report = await suite(FilteringRetriever())
    assert not any(v.query_id == "self:deals-x#b:0" for v in report.vacuous)


async def test_a_reranker_that_adds_a_chunk_is_caught_at_the_rerank_stage() -> None:
    report = await suite(FilteringRetriever(), InjectingReranker(), entitlements=[REP])
    assert {(v.stage, v.chunk_id) for v in report.violations} == {("rerank", "deals-x#b:0")}


async def test_golden_queries_without_an_expected_chunk_only_need_some_result() -> None:
    golden = [Query("q-0001", "anything at all")]
    ok = await run_permission_suite(
        FilteringRetriever(),
        None,
        index_version=1,
        entitlements=[REP, NOBODY],
        queries=golden,
        chunk_modules=CHUNKS,
    )
    assert ok.passed
    empty = await run_permission_suite(
        EmptyRetriever(),
        None,
        index_version=1,
        entitlements=[REP],
        queries=golden,
        chunk_modules=CHUNKS,
    )
    assert [(v.query_id, v.entitlement) for v in empty.vacuous] == [("q-0001", "rep@acme")]


# --- building the matrix and the queries ----------------------------------------------------


def test_the_matrix_has_every_persona_edge_sets_and_bogus_names() -> None:
    personas = {
        "rep@acme": frozenset({"core", "deals"}),
        "rep@globex": frozenset({"core", "deals"}),  # same set as rep@acme: kept once
        "mgr@acme": frozenset({"core", "deals", "campaigns"}),
    }
    matrix = entitlement_matrix(personas, ["core", "deals", "campaigns"])
    by_name = {e.name: e.allowed for e in matrix}
    assert by_name["rep@acme"] == {"core", "deals"} and "rep@globex" not in by_name
    assert by_name["mgr@acme"] == {"core", "deals", "campaigns"}
    assert by_name["nothing"] == frozenset()
    assert by_name["only:core"] == {"core"}
    assert by_name["only:campaigns"] == {"campaigns"}
    assert by_name["only:deals"] == {"deals"}
    assert "all" not in by_name, "all three modules = mgr@acme's set, kept once"
    assert by_name["bogus-only"] == frozenset(BOGUS_MODULES)
    assert by_name["core+bogus"] == {"core", *BOGUS_MODULES}
    assert len({e.allowed for e in matrix}) == len(matrix), "no duplicate sets"


def test_self_retrieval_makes_one_query_per_chunk_asking_for_it() -> None:
    qs = self_retrieval_queries([("d#a:0", "Doc > A\n\ntext a"), ("d#b:0", "Doc > B\n\ntext b")])
    assert qs == [
        Query("self:d#a:0", "Doc > A\n\ntext a", expect_chunk="d#a:0"),
        Query("self:d#b:0", "Doc > B\n\ntext b", expect_chunk="d#b:0"),
    ]
