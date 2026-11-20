"""Retrieval evals and the permission suite on an index version: `make eval` (live),
`make eval V=3`, or `make eval-baseline` to also refresh evals/baselines/retrieval.*.

Prints recall@k, complete recall@k and MRR per category for hybrid search and for
hybrid + rerank, the threshold check, and the zero-tolerance permission suite; saves
JSON + Markdown to evals/reports/retrieval/. No LLM. Exits non-zero on any leak. The
first run fills the rerank cache (minutes); later runs take about a minute.
"""

import argparse
import asyncio
import dataclasses
import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import yaml

from chatbot.adapters.local_catalogue import load_catalogue
from chatbot.adapters.st_embedder import SentenceTransformerEmbedder
from chatbot.config import Settings
from chatbot.db import libpq_url
from chatbot.evals import permissions
from chatbot.evals.golden import GoldenError
from chatbot.evals.labels import ChunkRow, OrphanLabels, label_index
from chatbot.evals.retrieval import load_golden, render_markdown, run_retrieval_eval
from chatbot.models_config import load_models_config
from chatbot.ports.embedder import Embedder
from chatbot.ports.retriever import NoLiveIndex
from chatbot.retrieval.hybrid import PgHybridRetriever, make_pool
from chatbot.retrieval.rerank import CrossEncoderReranker
from chatbot.retrieval.rerank_cache import CachingReranker

GOLDEN = sorted(Path("evals/golden").glob("*.yaml"))
REPORTS = Path("evals/reports/retrieval")
BASELINE = Path("evals/baselines/retrieval")


class MemoEmbedder:
    """The same texts are searched under many entitlement sets: embed each once per run."""

    def __init__(self, inner: Embedder) -> None:
        self._inner = inner
        self._memo: dict[str, list[float]] = {}
        self.key, self.dim = inner.key, inner.dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        missing = [t for t in dict.fromkeys(texts) if t not in self._memo]
        self._memo.update(zip(missing, self._inner.embed(missing), strict=True))
        return [self._memo[t] for t in texts]

    def count_tokens(self, text: str) -> int:
        return self._inner.count_tokens(text)


def _git() -> str:
    def out(*args: str) -> str:
        argv = ["git", *args]
        return subprocess.run(argv, capture_output=True, text=True, check=True).stdout.strip()  # noqa: S603

    try:
        sha, dirty = out("rev-parse", "--short", "HEAD"), out("status", "--porcelain")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return sha + ("-dirty" if dirty else "")


async def main(version: int | None, *, baseline: bool) -> int:
    settings = Settings()
    config = load_models_config(settings.models_path)
    if config.embeddings is None or config.reranker is None:
        print("config/models.yaml needs `embeddings:` and `reranker:`", file=sys.stderr)
        return 1
    try:
        golden = load_golden(GOLDEN)
    except GoldenError as e:
        print(f"ABORTED: {e}", file=sys.stderr)
        return 1
    personas = {
        p: frozenset(m)
        for p, m in yaml.safe_load(settings.personas_path.read_text())["personas"].items()
    }
    started = time.monotonic()
    async with make_pool(libpq_url(settings.database_url.get_secret_value())) as pool:
        embedder = MemoEmbedder(SentenceTransformerEmbedder(config.embeddings))
        retriever = PgHybridRetriever(pool, embedder)
        reranker = CachingReranker(CrossEncoderReranker(config.reranker), pool)
        try:
            v = version if version is not None else await retriever.live_version()
        except NoLiveIndex as e:
            print(f"ABORTED: {e}", file=sys.stderr)
            return 1
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT chunk_id, doc_id, anchor, parent_anchor, modules, "
                "breadcrumb || E'\\n\\n' || content FROM chunks WHERE index_version = %s "
                "ORDER BY chunk_id",
                (v,),
            )
            fetched = await cur.fetchall()
            rows = [ChunkRow(*r[:4]) for r in fetched]
            chunk_modules = {r[0]: tuple(r[4]) for r in fetched}
            self_queries = permissions.self_retrieval_queries([(r[0], r[5]) for r in fetched])
            recipe_row = await (
                await conn.execute(
                    "SELECT recipe FROM index_versions WHERE index_version = %s", (v,)
                )
            ).fetchone()
        if not rows or recipe_row is None:
            print(f"ABORTED: index version {v} has no chunks", file=sys.stderr)
            return 1
        try:
            run = await run_retrieval_eval(
                golden,
                personas,
                retriever,
                reranker,
                label_index(rows),
                index_version=v,
                threshold=config.reranker.threshold,
            )
        except (OrphanLabels, GoldenError) as e:
            print(f"ABORTED: {e}", file=sys.stderr)
            return 1
        # Hybrid stage only: the reranker can only reorder its input (unit tested), and
        # reranking 275 long queries x 26 sets first time would take ~15 minutes.
        catalogue_modules = sorted(load_catalogue(settings.catalogue_path).modules)
        matrix = permissions.entitlement_matrix(personas, catalogue_modules)
        queries = [permissions.Query(q.id, q.question) for q in golden] + self_queries
        perm = await permissions.run_permission_suite(
            retriever,
            None,
            index_version=v,
            entitlements=matrix,
            queries=queries,
            chunk_modules=chunk_modules,
        )

    now = datetime.now(UTC)
    header = {
        "run at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "git": _git(),
        "golden": ", ".join(str(p) for p in GOLDEN),
        "golden sha256": hashlib.sha256(b"".join(p.read_bytes() for p in GOLDEN)).hexdigest()[:16],
        "questions / pairs": f"{len(golden)} / {len(run.pairs)}",
        "embedder": config.embeddings.key,
        "reranker": config.reranker.key,
        "chunker": recipe_row[0].get("chunker_config_hash"),
        "took": f"{time.monotonic() - started:.0f}s",
    }
    report = (
        render_markdown(run, header)
        + "\n"
        + permissions.render_markdown(perm, entitlements=len(matrix), queries=len(queries))
    )
    perm_json = {
        "passed": perm.passed,
        "searches": perm.searches,
        "checked": perm.checked,
        "violations": [dataclasses.asdict(x) for x in perm.violations],
        "vacuous": [dataclasses.asdict(x) for x in perm.vacuous],
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    stem = REPORTS / f"{now:%Y%m%dT%H%M%SZ}-v{v}"
    stem.with_suffix(".md").write_text(report)
    summary = {
        "header": header,
        "index_version": v,
        "recipe": recipe_row[0],
        "threshold": run.threshold,
        "summaries": {
            stage: {cat: dataclasses.asdict(s) for cat, s in cats.items()}
            for stage, cats in run.summaries.items()
        },
        "gate": {g: dataclasses.asdict(c) for g, c in run.gate.items()},
        "permissions": perm_json,
    }
    full = {**summary, "pairs": [dataclasses.asdict(p) for p in run.pairs]}
    stem.with_suffix(".json").write_text(json.dumps(full, indent=1))
    print(report)
    print(f"saved {stem}.md and .json")
    if baseline:  # committed on purpose: no per-pair rankings, just the numbers
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.with_suffix(".md").write_text(report)
        BASELINE.with_suffix(".json").write_text(json.dumps(summary, indent=1) + "\n")
        print(f"baseline written to {BASELINE}.md and .json")
    if not perm.passed:
        print("PERMISSION SUITE FAILED: zero tolerance", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", type=int, help="index version (default: the live one)")
    parser.add_argument("--baseline", action="store_true", help="also write evals/baselines/")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.version, baseline=args.baseline)))
