# Retrieval eval: index v2

- run at: `2026-11-20 10:33 UTC`
- git: `bb6c36e-dirty`
- golden: `evals/golden/synthetic_v1.yaml`
- golden sha256: `e227d2aad9f7856b`
- questions / pairs: `151 / 411`
- embedder: `BAAI/bge-m3@5617a9f61b02`
- reranker: `BAAI/bge-reranker-v2-m3@953dc6f6f85a`
- chunker: `dd7646f795c452b1`
- took: `51s`

## Hybrid + rerank

| category | n | recall@1 | recall@3 | recall@5 | recall@10 | complete@1 | complete@3 | complete@5 | complete@10 | MRR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| single | 120 | 0.88 | 0.98 | 1.00 | 1.00 | 0.88 | 0.98 | 1.00 | 1.00 | 0.94 |
| multi_hop | 52 | 0.23 | 0.58 | 0.76 | 0.96 | 0.00 | 0.21 | 0.56 | 0.92 | 0.70 |
| restricted | 20 | 0.80 | 1.00 | 1.00 | 1.00 | 0.80 | 1.00 | 1.00 | 1.00 | 0.89 |
| adversarial | 15 | 0.87 | 1.00 | 1.00 | 1.00 | 0.87 | 1.00 | 1.00 | 1.00 | 0.92 |
| **overall** | 207 | 0.71 | 0.88 | 0.94 | 0.99 | 0.65 | 0.79 | 0.89 | 0.98 | 0.87 |

## Hybrid only

| category | n | recall@1 | recall@3 | recall@5 | recall@10 | complete@1 | complete@3 | complete@5 | complete@10 | MRR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| single | 120 | 0.72 | 0.95 | 0.98 | 1.00 | 0.72 | 0.95 | 0.98 | 1.00 | 0.84 |
| multi_hop | 52 | 0.32 | 0.63 | 0.78 | 0.91 | 0.00 | 0.40 | 0.58 | 0.83 | 0.77 |
| restricted | 20 | 0.55 | 0.90 | 0.95 | 1.00 | 0.55 | 0.90 | 0.95 | 1.00 | 0.73 |
| adversarial | 15 | 0.67 | 0.87 | 0.93 | 1.00 | 0.67 | 0.87 | 0.93 | 1.00 | 0.78 |
| **overall** | 207 | 0.60 | 0.86 | 0.93 | 0.98 | 0.52 | 0.80 | 0.87 | 0.96 | 0.81 |

## Threshold 0.3 on the top rerank score

| expected | n | above threshold | |
|---|---:|---:|---|
| answer | 207 | 189 | 91.3% kept (should be ~100%) |
| restricted | 144 | 23 | 84.0% refused (rest: partial access, S3.1.3b) |
| not found / out of scope | 60 | 2 | 96.7% refused (should be ~100%) |

## Permission suite (zero tolerance)

PASS: 7150 searches (26 entitlement sets x 275 queries), 107525 candidates checked, 0 leaks, 0 vacuous results.
