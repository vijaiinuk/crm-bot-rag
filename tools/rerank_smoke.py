"""Load bge-reranker-v2-m3 (downloads ~2.3 GB the first time) and sanity-check it:
`make rerank-smoke`. Prints the latency of reranking 20 candidates on this machine."""

import asyncio
import sys
import time

from chatbot.config import Settings
from chatbot.models_config import load_models_config
from chatbot.ports.retriever import Candidate
from chatbot.retrieval.rerank import CrossEncoderReranker

QUERY = "How do I move a deal to another pipeline stage?"
RELEVANT = "Drag the deal card to a different stage column on the pipeline board."
OTHER = "Reset your password from the sign-in page if you have forgotten it."


def cand(i: int, text: str) -> Candidate:
    return Candidate(f"d#s{i}:0", "d", f"s{i}", "Doc > Section", text, ("core",), 0, i, None, 0.0)


async def main() -> int:
    config = load_models_config(Settings().models_path).reranker
    if config is None:
        print("config/models.yaml has no `reranker:` section", file=sys.stderr)
        return 1
    r = CrossEncoderReranker(config)
    started = time.monotonic()
    best = await r.rerank(QUERY, [cand(0, OTHER), cand(1, RELEVANT)], 2)
    loaded = time.monotonic() - started
    twenty = [cand(i, RELEVANT if i == 7 else f"{OTHER} Variant {i}.") for i in range(20)]
    started = time.monotonic()
    await r.rerank(QUERY, twenty, 20)
    per_query = time.monotonic() - started
    ok = best[0].content == RELEVANT and (best[0].rerank_score or 0) > (best[1].rerank_score or 0)
    print(
        f"{r.key}: relevant {best[0].rerank_score:.3f} vs other {best[1].rerank_score:.3f} "
        f"(first call incl. load {loaded:.1f}s); 20 candidates in {per_query * 1000:.0f} ms"
    )
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
