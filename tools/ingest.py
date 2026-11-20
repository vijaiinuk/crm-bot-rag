"""Index versions from data/docs: `make ingest`, `make index-list`, `make promote V=n`,
`make rollback`, `make embed-smoke`.

`build` validates, chunks and embeds (cache first) into a new index version. With
`--promote` it then runs the publish gate (S2.4.1: orphaned labels, permission suite,
recall regression vs live, module widening) and goes live only if the gate passes.
There is no way to skip the gate.
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

import psycopg

from chatbot.adapters.local_catalogue import load_catalogue
from chatbot.adapters.memo_embedder import MemoEmbedder
from chatbot.adapters.st_embedder import SentenceTransformerEmbedder
from chatbot.config import Settings
from chatbot.db import libpq_url
from chatbot.evals import permissions
from chatbot.evals.retrieval import load_golden
from chatbot.ingest.build import (
    BuildFailed,
    PromotionError,
    build_index,
    list_versions,
    promote,
    record_gate,
    rollback,
)
from chatbot.ingest.chunker import Chunker
from chatbot.ingest.gate import GateReport, load_gate_config, run_gate
from chatbot.ingest.validate import DocValidator, IngestAborted, load_frontmatter_schema
from chatbot.models_config import load_models_config
from chatbot.retrieval.hybrid import PgHybridRetriever, make_pool
from chatbot.retrieval.rerank import CrossEncoderReranker
from chatbot.retrieval.rerank_cache import CachingReranker

DOCS = Path("data/docs")
SCHEMA = Path("data/spec/doc_frontmatter.schema.json")
GOLDEN = sorted(Path("evals/golden").glob("*.yaml"))
GATE_CONFIG = Path("config/gate.yaml")


def _embedder(settings: Settings) -> SentenceTransformerEmbedder:
    config = load_models_config(settings.models_path).embeddings
    if config is None:
        raise SystemExit(f"{settings.models_path} has no `embeddings:` section")
    return SentenceTransformerEmbedder(config)


def _connect(settings: Settings) -> psycopg.Connection[tuple[object, ...]]:
    try:
        return psycopg.connect(libpq_url(settings.database_url.get_secret_value()), autocommit=True)
    except psycopg.OperationalError as e:
        raise SystemExit(f"cannot reach Postgres (run `make up`): {e}") from e


async def gate(settings: Settings, version: int, live: int | None, *, confirm: bool) -> GateReport:
    config = load_models_config(settings.models_path)
    if config.embeddings is None or config.reranker is None:
        raise SystemExit(f"{settings.models_path} needs `embeddings:` and `reranker:`")
    personas = settings.load_personas()
    matrix = permissions.entitlement_matrix(
        personas, sorted(load_catalogue(settings.catalogue_path).modules)
    )
    async with make_pool(libpq_url(settings.database_url.get_secret_value())) as pool:
        return await run_gate(
            pool,
            version,
            live,
            retriever=PgHybridRetriever(
                pool, MemoEmbedder(SentenceTransformerEmbedder(config.embeddings))
            ),
            reranker=CachingReranker(CrossEncoderReranker(config.reranker), pool),
            golden=load_golden(GOLDEN),
            personas=personas,
            entitlements=matrix,
            threshold=config.reranker.threshold,
            config=load_gate_config(GATE_CONFIG),
            confirm_widening=confirm,
        )


def print_gate(report: GateReport) -> None:
    print(f"gate for version {report.version} (vs live {report.live_version or 'none'}):")
    if report.orphans:
        print(f"  orphaned labels: {', '.join(report.orphans)}")
    if report.permissions:
        p = report.permissions
        print(
            f"  permissions: {p['searches']} searches, {p['checked']} candidates, "
            f"{len(p['violations'])} leaks, {len(p['vacuous'])} vacuous"
        )
    if report.regression:
        r = report.regression
        if "live" in r:
            changes = ", ".join(f"{m} {r['live'][m]:.3f} -> {r['new'][m]:.3f}" for m in r["new"])
            print(f"  regression (tolerance {r['tolerance']}): {changes}")
        else:
            print(f"  regression: {r.get('note')}")
    if report.widening:
        w = report.widening
        print(
            f"  widening: {len(w['widened'])} widened, {len(w['new_docs'])} new docs"
            + (" (confirmed)" if w["confirmed"] else "")
        )
    print("  PASSED" if report.passed else "  FAILED:\n    " + "\n    ".join(report.failures))


def cmd_build(
    settings: Settings, *, promote_after: bool, docs_dir: Path = DOCS, confirm: bool = False
) -> int:
    started = time.monotonic()
    catalogue = load_catalogue(settings.catalogue_path)
    validator = DocValidator(frozenset(catalogue.modules), load_frontmatter_schema(SCHEMA))
    try:
        docs = validator.read_corpus(docs_dir)
    except IngestAborted as e:
        print(f"ABORTED, nothing written. {e}", file=sys.stderr)
        return 1
    embedder = _embedder(settings)
    chunker = Chunker(embedder.count_tokens, tokenizer_name=embedder.key)
    with _connect(settings) as conn:
        try:
            r = build_index(conn, docs, chunker=chunker, embedder=embedder, catalogue=catalogue)
        except IngestAborted as e:
            print(f"ABORTED, nothing written. {e}", file=sys.stderr)
            return 1
        except BuildFailed as e:
            print(f"FAILED: {e}. The live index is unchanged.", file=sys.stderr)
            return 1
        print(
            f"built index version {r.index_version}: {r.doc_count} docs, {r.chunk_count} chunks; "
            f"embedded {r.embedded}, reused {r.reused} from cache "
            f"({time.monotonic() - started:.1f}s)"
        )
        if promote_after:
            live = next((v.index_version for v in list_versions(conn) if "live" in v.aliases), None)
            report = asyncio.run(gate(settings, r.index_version, live, confirm=confirm))
            record_gate(conn, r.index_version, report.to_json())
            print_gate(report)
            if not report.passed:
                print(f"version {r.index_version} NOT promoted; live stays {live}", file=sys.stderr)
                return 1
            promote(conn, r.index_version)
            print(f"version {r.index_version} is live")
    return 0


def cmd_list(settings: Settings) -> int:
    with _connect(settings) as conn:
        rows = list_versions(conn)
    if not rows:
        print("no index versions yet: make ingest")
    for v in rows:
        live = f"  <- {', '.join(v.aliases)}" if v.aliases else ""
        counts = f"{v.chunk_count} chunks, embedded {v.embedded}, reused {v.reused}"
        flags = " ungated" if v.ungated else ""
        error = f"  ({v.error})" if v.error else ""
        print(
            f"{v.index_version:>4}  {v.status:<10} {v.created_at:%Y-%m-%d %H:%M}  "
            f"{counts}{flags}{live}{error}"
        )
    return 0


def cmd_promote(settings: Settings, version: int) -> int:
    with _connect(settings) as conn:
        try:
            promote(conn, version)
        except PromotionError as e:
            print(f"REFUSED: {e}", file=sys.stderr)
            return 1
    print(f"version {version} is live")
    return 0


def cmd_rollback(settings: Settings) -> int:
    with _connect(settings) as conn:
        try:
            now = rollback(conn)
        except PromotionError as e:
            print(f"REFUSED: {e}", file=sys.stderr)
            return 1
    print(f"rolled back: version {now} is live")
    return 0


def cmd_embed_smoke(settings: Settings) -> int:
    """Loads the real model (downloads it the first time) and checks it behaves."""
    import numpy as np

    embedder = _embedder(settings)
    started = time.monotonic()
    a, b, c = embedder.embed(
        [
            "How do I move a deal to another pipeline stage?",
            "Drag the deal card to a different stage column on the board.",
            "Reset your password from the sign-in page.",
        ]
    )
    norms = [float(np.linalg.norm(v)) for v in (a, b, c)]
    related, unrelated = float(np.dot(a, b)), float(np.dot(a, c))
    print(
        f"{embedder.key}: dim {len(a)}, norms {[round(n, 3) for n in norms]}, "
        f"related {related:.3f} > unrelated {unrelated:.3f} "
        f"({time.monotonic() - started:.1f}s incl. load)"
    )
    ok = len(a) == embedder.dim and all(abs(n - 1) < 1e-3 for n in norms) and related > unrelated
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build a new index version from data/docs")
    b.add_argument("--promote", action="store_true", help="then gate it; live only if it passes")
    b.add_argument("--docs", type=Path, default=DOCS, help="docs directory (default data/docs)")
    b.add_argument("--confirm-widening", action="store_true", help="accept docs that drop a module")
    sub.add_parser("list", help="list index versions")
    p = sub.add_parser("promote", help="make a version that passed the gate live")
    p.add_argument("version", type=int)
    sub.add_parser("rollback", help="undo the last repoint of the live alias")
    sub.add_parser("embed-smoke", help="load the real embedding model and sanity-check it")
    args = parser.parse_args(argv)
    settings = Settings()
    match args.cmd:
        case "build":
            return cmd_build(
                settings,
                promote_after=args.promote,
                docs_dir=args.docs,
                confirm=args.confirm_widening,
            )
        case "list":
            return cmd_list(settings)
        case "promote":
            return cmd_promote(settings, args.version)
        case "rollback":
            return cmd_rollback(settings)
        case _:
            return cmd_embed_smoke(settings)


if __name__ == "__main__":
    sys.exit(main())
