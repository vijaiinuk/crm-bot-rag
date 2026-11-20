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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chatbot.adapters.local_catalogue import load_catalogue
from chatbot.adapters.memo_embedder import MemoEmbedder
from chatbot.adapters.st_embedder import SentenceTransformerEmbedder
from chatbot.config import Settings
from chatbot.db import libpq_url
from chatbot.evals import permissions
from chatbot.evals.golden import GoldenError
from chatbot.evals.labels import OrphanLabels
from chatbot.evals.retrieval import load_golden, render_markdown
from chatbot.evals.runner import VersionEval, VersionNotFound, evaluate_version
from chatbot.models_config import load_models_config
from chatbot.ports.retriever import NoLiveIndex
from chatbot.retrieval.hybrid import PgHybridRetriever, make_pool
from chatbot.retrieval.rerank import CrossEncoderReranker
from chatbot.retrieval.rerank_cache import CachingReranker

GOLDEN = sorted(Path("evals/golden").glob("*.yaml"))
REPORTS = Path("evals/reports/retrieval")
BASELINE = Path("evals/baselines/retrieval")


def git_describe() -> str:
    def out(*args: str) -> str:
        argv = ["git", *args]
        return subprocess.run(argv, capture_output=True, text=True, check=True).stdout.strip()  # noqa: S603

    try:
        sha, dirty = out("rev-parse", "--short", "HEAD"), out("status", "--porcelain")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return sha + ("-dirty" if dirty else "")


def golden_sha() -> str:
    return hashlib.sha256(b"".join(p.read_bytes() for p in GOLDEN)).hexdigest()[:16]


def summary_json(ev: VersionEval) -> dict[str, Any]:
    """The numbers without per-pair rankings: what the baseline and the gate report keep."""
    out: dict[str, Any] = {
        "index_version": ev.version,
        "recipe": ev.recipe,
        "threshold": ev.run.threshold,
        "summaries": {
            stage: {cat: dataclasses.asdict(s) for cat, s in cats.items()}
            for stage, cats in ev.run.summaries.items()
        },
        "gate": {g: dataclasses.asdict(c) for g, c in ev.run.gate.items()},
    }
    if ev.permissions is not None:
        p = ev.permissions
        out["permissions"] = {
            "passed": p.passed,
            "searches": p.searches,
            "checked": p.checked,
            "violations": [dataclasses.asdict(x) for x in p.violations[:200]],
            "vacuous": [dataclasses.asdict(x) for x in p.vacuous[:200]],
        }
    return out


async def main(version: int | None, *, baseline: bool) -> int:
    settings = Settings()
    config = load_models_config(settings.models_path)
    if config.embeddings is None or config.reranker is None:
        print("config/models.yaml needs `embeddings:` and `reranker:`", file=sys.stderr)
        return 1
    started = time.monotonic()
    try:
        golden = load_golden(GOLDEN)
        personas = settings.load_personas()
        matrix = permissions.entitlement_matrix(
            personas, sorted(load_catalogue(settings.catalogue_path).modules)
        )
        async with make_pool(libpq_url(settings.database_url.get_secret_value())) as pool:
            retriever = PgHybridRetriever(
                pool, MemoEmbedder(SentenceTransformerEmbedder(config.embeddings))
            )
            reranker = CachingReranker(CrossEncoderReranker(config.reranker), pool)
            v = version if version is not None else await retriever.live_version()
            ev = await evaluate_version(
                pool,
                v,
                retriever=retriever,
                reranker=reranker,
                golden=golden,
                personas=personas,
                threshold=config.reranker.threshold,
                entitlements=matrix,
            )
    except (GoldenError, OrphanLabels, NoLiveIndex, VersionNotFound) as e:
        print(f"ABORTED: {e}", file=sys.stderr)
        return 1
    if ev.permissions is None:  # entitlements were passed, so this cannot happen
        raise RuntimeError("permission suite did not run")

    now = datetime.now(UTC)
    header = {
        "run at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "git": git_describe(),
        "golden": ", ".join(str(p) for p in GOLDEN),
        "golden sha256": golden_sha(),
        "questions / pairs": f"{len(golden)} / {len(ev.run.pairs)}",
        "embedder": config.embeddings.key,
        "reranker": config.reranker.key,
        "chunker": ev.recipe.get("chunker_config_hash"),
        "took": f"{time.monotonic() - started:.0f}s",
    }
    report = (
        render_markdown(ev.run, header)
        + "\n"
        + permissions.render_markdown(ev.permissions, entitlements=len(matrix), queries=ev.queries)
    )
    summary = {"header": header, **summary_json(ev)}
    REPORTS.mkdir(parents=True, exist_ok=True)
    stem = REPORTS / f"{now:%Y%m%dT%H%M%SZ}-v{v}"
    stem.with_suffix(".md").write_text(report)
    full = {**summary, "pairs": [dataclasses.asdict(p) for p in ev.run.pairs]}
    stem.with_suffix(".json").write_text(json.dumps(full, indent=1))
    print(report)
    print(f"saved {stem}.md and .json")
    if baseline:  # committed on purpose: no per-pair rankings, just the numbers
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.with_suffix(".md").write_text(report)
        BASELINE.with_suffix(".json").write_text(json.dumps(summary, indent=1) + "\n")
        print(f"baseline written to {BASELINE}.md and .json")
    if not ev.permissions.passed:
        print("PERMISSION SUITE FAILED: zero tolerance", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", type=int, help="index version (default: the live one)")
    parser.add_argument("--baseline", action="store_true", help="also write evals/baselines/")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.version, baseline=args.baseline)))
