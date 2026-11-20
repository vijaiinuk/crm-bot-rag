"""Retrieval evals on an index version: `make eval` (live) or `make eval V=3`.

Prints recall@k, complete recall@k and MRR per category for hybrid search and for
hybrid + rerank, plus the threshold check, and saves JSON + Markdown to
evals/reports/retrieval/. No LLM. The first run fills the rerank cache (minutes);
later runs take seconds.
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

import yaml

from chatbot.adapters.st_embedder import SentenceTransformerEmbedder
from chatbot.config import Settings
from chatbot.db import libpq_url
from chatbot.evals.golden import GoldenError
from chatbot.evals.labels import ChunkRow, OrphanLabels, label_index
from chatbot.evals.retrieval import load_golden, render_markdown, run_retrieval_eval
from chatbot.models_config import load_models_config
from chatbot.ports.retriever import NoLiveIndex
from chatbot.retrieval.hybrid import PgHybridRetriever, make_pool
from chatbot.retrieval.rerank import CrossEncoderReranker
from chatbot.retrieval.rerank_cache import CachingReranker

GOLDEN = sorted(Path("evals/golden").glob("*.yaml"))
REPORTS = Path("evals/reports/retrieval")


def _git() -> str:
    def out(*args: str) -> str:
        argv = ["git", *args]
        return subprocess.run(argv, capture_output=True, text=True, check=True).stdout.strip()  # noqa: S603

    try:
        sha, dirty = out("rev-parse", "--short", "HEAD"), out("status", "--porcelain")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return sha + ("-dirty" if dirty else "")


async def main(version: int | None) -> int:
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
        retriever = PgHybridRetriever(pool, SentenceTransformerEmbedder(config.embeddings))
        reranker = CachingReranker(CrossEncoderReranker(config.reranker), pool)
        try:
            v = version if version is not None else await retriever.live_version()
        except NoLiveIndex as e:
            print(f"ABORTED: {e}", file=sys.stderr)
            return 1
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT chunk_id, doc_id, anchor, parent_anchor FROM chunks "
                "WHERE index_version = %s",
                (v,),
            )
            rows = [ChunkRow(*r) for r in await cur.fetchall()]
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
    report = render_markdown(run, header)
    REPORTS.mkdir(parents=True, exist_ok=True)
    stem = REPORTS / f"{now:%Y%m%dT%H%M%SZ}-v{v}"
    stem.with_suffix(".md").write_text(report)
    stem.with_suffix(".json").write_text(
        json.dumps(
            {
                "header": header,
                "index_version": v,
                "recipe": recipe_row[0],
                "threshold": run.threshold,
                "summaries": {
                    stage: {cat: dataclasses.asdict(s) for cat, s in cats.items()}
                    for stage, cats in run.summaries.items()
                },
                "gate": {g: dataclasses.asdict(c) for g, c in run.gate.items()},
                "pairs": [dataclasses.asdict(p) for p in run.pairs],
            },
            indent=1,
        )
    )
    print(report)
    print(f"saved {stem}.md and .json")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", type=int, help="index version (default: the live one)")
    sys.exit(asyncio.run(main(parser.parse_args().version)))
