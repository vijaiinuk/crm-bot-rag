# ADR-0001: Postgres for vector and keyword search

- Status: accepted
- Date: 2026-11-12

## Context
Retrieval is hybrid: semantic plus keyword, with a module permission filter that must be applied inside the query (rule 2), never after ranking. The corpus is at most ~100 markdown docs (≈3–5k chunks). Production runs on AWS.

## Decision
- One **Postgres 16** database holds chunks, embeddings (**pgvector**) and the keyword index (**built-in full-text search**: generated `tsvector`, GIN index).
- Vector search is **exact** (no HNSW or IVF index). At this size a full scan takes milliseconds and has perfect recall.
- Keyword ranking uses `ts_rank_cd`. Results are fused with **reciprocal rank fusion** (k = 60).
- Both queries apply `modules <@ :allowed` in their `WHERE` clause.
- There is no upload-date filter: only the latest published version of each doc is live, so stale versions are never retrievable.

## Alternatives
- **Dedicated vector DB** (Pinecone, Qdrant, Weaviate): a second store to keep in sync and secure; the permission filter would be split across systems. Not justified at 5k chunks.
- **Azure AI Search / OpenSearch:** real BM25 and managed hybrid search, but production is AWS, and the permission filter would move into another service's query language.
- **ParadeDB `pg_search`** (real BM25 inside Postgres): the upgrade path, if keyword-recall evals show that `ts_rank_cd` loses relevant chunks.

## Consequences
- `ts_rank_cd` is not BM25: it has no IDF term and only crude length normalisation. RRF uses rank order only, which limits the damage. The keyword-recall evals are the trigger for revisiting this.
- Everything runs on one RDS for PostgreSQL instance in production, with one backup and one security model.
- If the corpus grows past ~100k chunks, add an HNSW index and re-measure recall.
