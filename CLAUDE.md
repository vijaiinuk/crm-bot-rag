# CLAUDE.md

Context for Claude Code sessions on this repo. Read fully before proposing changes.

## What this is

A RAG help chatbot for an existing multi-tenant CRM (React + Python monolith, hosted on a third-party cloud). Users from client companies ask how to use CRM modules; the bot answers from product documentation with citations.

**Current phase: MVP demo, solo developer, local only.** No cloud deployment. Synthetic documents and eval data stand in for real CRM docs until the CRM team supplies them. Goal: prove quality, permission safety and measurability to the business, on a codebase that can be productionised rather than rewritten.

The week-by-week plan uses story IDs like `S2.1.3`. When asked to implement a story, scope work to that story only.

## Non-negotiable rules

These are correctness and security invariants. Never relax them, even temporarily, even in tests (except tests that assert they fail correctly).

1. **Entitlements come only from the verified JWT.** Tenant, user and role are read from the validated token; allowed modules are resolved server-side via `EntitlementProvider`. Never accept modules, tenant or role from the request body or query string.
2. **Filter before ranking.** Every retrieval query (vector and full-text, every sub-query, every follow-up) applies `modules <@ :allowed_modules` inside the SQL. Never post-filter top-k results.
3. **Restricted content never enters the prompt.** No "retrieve everything and tell the model not to mention it". Authorization is code, not prompt.
4. **Fail closed.** Untagged chunks, unknown module names, or an unreachable entitlement source mean deny/abort, never allow-all. Ingestion aborts the whole run on any tagging error.
5. **Chunk visibility requires all of its modules.** A chunk tagged `[deals, campaigns]` is visible only if both are allowed.
6. **The permission eval suite is zero tolerance.** One leak fails the build. Quality evals use thresholds; permission evals do not.
7. **Restricted-module responses are templated** from `module_catalogue`, never LLM-generated from restricted content.
8. **Every request is traced** with the entitlement set, index version, prompt version, model ID and token counts.

## Architecture

### Query path (`POST /chat`, SSE streaming)

1. Validate JWT against JWKS -> resolve allowed modules (TTL cache).
2. Input guardrails: rate limit per user/tenant, scope check. Redact PII before logging.
3. Rewrite (skip on first turn): one small-model call returning structured output `{standalone: str, sub_queries: list[str]}` (0-3 sub-queries for cross-module questions). Validate with Pydantic. If a module hint list is given to the model, give only allowed modules.
4. For each query, in parallel: hybrid search = exact vector search + Postgres FTS, both with the module filter -> reciprocal rank fusion. Merge, dedupe by chunk ID.
5. Rerank against the standalone query with the cross-encoder. Apply per-module diversity, then parent-section expansion.
6. If top rerank score < threshold: skip the LLM; return "not found" or the restricted-module template (module catalogue lookup).
7. Generate via LiteLLM: versioned prompt, static prefix first (for prompt caching), chunks labelled by chunk ID. Structured output `{answer, steps, citations}`.
8. Verify every cited chunk ID was in the context; drop or flag any that were not.
9. Stream the response; emit the trace.

### Ingestion path (offline, `make ingest`)

1. Read markdown docs + frontmatter. Validate against schema; unknown modules or missing tags abort the run.
2. Heading-aware chunking: split on headings, prefix breadcrumb (`Module > Section > Subsection`), never split numbered procedures, carry the section anchor onto each chunk.
3. Content-hash each chunk; embed only hashes missing from `embedding_cache`.
4. Write a complete new `index_version`; run retrieval + permission evals against it; promote the `active_index` pointer only if they pass. Rollback = repoint.

### Multi-hop policy

Supported: query decomposition (inside the rewrite call), per-module diversity, parent-section expansion. **Deferred:** iterative retrieve-then-reason loops. Do not add an agentic loop unless asked; evals (complete recall@k) decide.

## Stack and decisions

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.12, `uv` | ruff + mypy (strict) via pre-commit |
| API | FastAPI, async, SSE | pydantic v2, pydantic-settings |
| Store | Postgres 16 + pgvector + FTS | **exact search, no HNSW/IVF index** at this scale |
| Migrations | Alembic | |
| Embeddings | `bge-m3` via sentence-transformers, MPS | multilingual on purpose (future scope) |
| Reranker | `bge-reranker-v2-m3` cross-encoder, MPS | |
| LLM access | LiteLLM -> AWS Bedrock (Converse API) | pinned model IDs only, never "latest" aliases |
| Local LLM (bake-off only) | Ollama, native macOS | always set `num_ctx` (8192) explicitly |
| Tracing | OpenTelemetry -> Arize Phoenix | |
| UI | Vite + React standalone widget | must stay embeddable in the CRM later |
| Auth (local) | local RSA keypair + JWKS endpoint + persona JWT minting CLI | same validation code path as production |

**Deliberately not used:** LangChain, LlamaIndex or other orchestration frameworks (write the pipeline as plain functions behind interfaces); Bedrock Knowledge Bases; dedicated vector databases; reasoning/"thinking" models for answer generation; Redis (in-process TTL cache behind an interface for now).

### Model tiering

- Rewrite/decomposition: small, fast model.
- Answer generation: chosen by the model bake-off (S3.3.1); record in an ADR.
- LLM-as-judge: top-tier model from a **different provider** than the generator.
- Synthetic data: docs and questions generated by **different** models.

Model IDs live in config (`config/models.yaml`), never hardcoded.

## Core interfaces

Keep these as `typing.Protocol`s in `src/chatbot/ports/`. Production adapters replace local ones without upstream changes.

- `EntitlementProvider.resolve(claims) -> frozenset[str]` (local: reads `personas.yaml`; prod: CRM entitlement API)
- `Retriever.search(query, allowed_modules, k) -> list[Candidate]`
- `Reranker.rerank(query, candidates, k) -> list[Candidate]`
- `LLMClient.complete(prompt, schema, model) -> ParsedResponse`
- `Guardrail.check_input(...)` / `check_output(...)`

## Data formats (the contract for swapping in real data)

Synthetic generators are dev tools. These formats are the contract; real CRM docs and evals must use the same ones.

- **`data/spec/crm_spec.yaml`**: modules (entities, UI labels), roles -> modules, clients -> licensed modules, cross-module workflows. Validated by `data/spec/crm_spec.schema.json`.
- **`data/personas.yaml`**: persona ID (`role@client`) -> allowed modules (licensed ∩ role-permitted, plus `core`).
- **Docs** (`data/docs/**/*.md`) frontmatter:
  ```yaml
  doc_id: deals-stage-automation
  title: Automating deal stage changes
  modules: [deals]          # every doc needs >=1 known module; `core` for shared content
  version: 1
  ```
  Section anchors are stable slugs of headings; do not rename anchors casually (evals reference them).
- **Evals** (`evals/golden/*.yaml`): label against `doc_id#anchor`, never chunk IDs.
  ```yaml
  - id: q-0042
    question: "how do i get an email sent when a deal moves to negotiation"
    category: multi_hop      # single | multi_hop | unanswerable | out_of_scope | restricted | adversarial
    expected:
      sales_manager@acme: { outcome: answer, required: [deals-stage-automation#triggers, campaigns-triggered-emails#setup] }
      sales_rep@globex:   { outcome: restricted, missing_modules: [campaigns] }
  ```
- Generated data is committed with its generator prompt version and seed. Do not regenerate as part of normal runs.

## Database (key tables)

`index_versions` (recipe: parser version, chunker config hash, embed model, status) · `active_index` (alias -> version) · `chunks` (chunk_id, index_version, doc_id, anchor, breadcrumb, content, `modules text[]`, nullable `required_permission`, embedding, generated tsvector, content_hash) · `embedding_cache` (content_hash, embed_model, embedding) · `module_catalogue` · `conversations` / `messages` / `feedback` keyed by trace_id. GIN index on `chunks.modules`.

## Proposed layout

```
src/chatbot/
  api/          # FastAPI routes, SSE, auth dependency
  ports/        # Protocols
  adapters/     # local + bedrock + ollama implementations
  ingest/       # validate, chunk, embed, index versions
  retrieval/    # hybrid search, fusion, rerank, diversity
  generation/   # prompts, structured output, citation check
  guardrails/
  tracing/
prompts/        # versioned prompt templates (prompt_id + version in filename)
config/         # models.yaml, settings
data/           # spec, personas, docs (synthetic for now)
evals/          # golden sets, harness, reports/
tools/          # generators, token minting CLI
tests/
docs/adr/
```

## Commands

```
make up        # docker compose: postgres+pgvector, phoenix
make down
make ingest    # build + evaluate + promote a new index version
make eval      # retrieval metrics + permission suite (fast, no LLM)
make eval-gen  # generation evals (LLM + judge; slower, costs money)
make test      # unit tests
make run       # API locally
```

## Environment constraints (MacBook Air M4, 16 GB)

- Docker runs **only** Postgres and Phoenix (VM capped ~3 GB). Docker on macOS has no GPU access.
- Python service, embedding model, reranker and Ollama run **natively** (MPS / Metal).
- Do not run Ollama during normal development; use Bedrock. Ollama is for bake-off sessions only.
- Laptop latency is not representative of production; never use it for self-hosting conclusions.

## Testing and evals

- **Unit tests:** parsers, chunker (snapshot tests on fixtures), filter construction, prompt assembly, citation verification. Mock the LLM.
- **Retrieval evals:** recall@k, **complete recall@k** (all required sections retrieved), MRR, per category. No LLM.
- **Permission suite:** assert `chunk.modules ⊆ persona.allowed` for every retrieved chunk across the persona matrix, plus Hypothesis property tests with random entitlement sets. Zero tolerance.
- **Generation evals:** faithfulness, correctness, refusal accuracy, citation accuracy. Judge calibrated against hand labels. Use Bedrock batch where possible. Gate on thresholds and regressions vs baseline, never exact match.
- Eval harness: retries with backoff and bounded concurrency (Bedrock quotas are low on new accounts).
- Every successful red-team attack becomes a permanent eval case.

## How to work with me (the developer)

- **One story per session.** Start in plan mode: propose the approach, files touched and tests; wait for approval before writing code.
- **Tests first** for the chunker, retrieval filter, eval metrics and permission suite: write failing tests from the story's "done when" line, let me review them, then implement.
- **I am learning RAG deliberately.** For the chunker, hybrid query + fusion, eval metrics and permission suite, explain the design and trade-offs and pair with me; do not silently write the whole thing. Boilerplate (compose, scaffolding, migrations, Makefile, token CLI, React widget) can be delegated fully.
- Be critical: point out flaws in my approach and explain why, rather than just complying.
- Small, focused commits per story. Do not refactor unrelated code.
- Never commit secrets; AWS credentials come from the local profile/env.
- If a change would touch a non-negotiable rule, stop and ask.

## Out of scope for the MVP

Word/PDF parsing, image captioning, real CRM entitlement API, CRM embedding, cloud deployment, multilingual UI, voice, iterative retrieval loop, semantic cache, post-hoc groundedness check, self-hosted LLM serving. Interfaces should leave room for these; do not build them.

## ADRs

Record significant decisions in `docs/adr/NNNN-title.md` (context, decision, alternatives, consequences). Existing decisions to record early: vector store (Postgres vs Azure AI Search), no orchestration framework, synthetic data strategy, model choice (after bake-off).
