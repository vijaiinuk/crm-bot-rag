# CLAUDE.md

Context for Claude Code sessions on this repo. Read fully before proposing changes.

## What this is

A RAG help chatbot for an existing multi-tenant CRM (React + Python monolith, hosted on AWS). Users from client companies ask how to use CRM modules; the bot answers from product documentation with citations. Your ops admins manage the docs, releases, evals and costs through a separate admin app.

**Architecture:** [`docs/architecture.md`](docs/architecture.md) (components, content lifecycle, data model, cost, evals). Read it before designing anything beyond the query path.

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
6. If top rerank score < threshold: skip the LLM; return "not found" or the restricted-module template. Which modules the user lacks a question concerns is decided only by embedding similarity to the **public** `module_catalogue` profiles (relative rule + floor), never by retrieving outside the allowed modules (rule 2).
7. Generate via LiteLLM, streamed: versioned prompt, static prefix first (for prompt caching), excerpts numbered `[1]..[n]` (mapped to chunk IDs server-side). Markdown answer with `[n]` citation markers, stripped from the stream; `[[NOT_FOUND]]` sentinel becomes the not-found refusal. Partial access (allowed docs answer, a lacking module is also involved): answer plus a templated catalogue note, never LLM-written.
8. Verify every cited marker was in the context; drop and count any that were not.
9. Stream the response; emit the trace.

### Ingestion path (admin publish, or `make ingest` for dev/CI)

Admins upload markdown (validated at upload) into a draft release; **publish** runs the steps below as a `build_release` job on the Postgres queue. Modules come **only from frontmatter**; there is no module assignment in the admin UI. A change that widens a doc's modules needs explicit publisher confirmation (audit-logged). See `docs/architecture.md` §4.

1. Read markdown docs + frontmatter. Validate against schema; unknown modules or missing tags abort the run.
2. Heading-aware chunking: split on headings, prefix breadcrumb (`Doc title > Section > Subsection`; modules stay in metadata, not the text), never split numbered procedures, carry the section anchor onto each chunk.
3. Content-hash each chunk; embed only hashes missing from `embedding_cache`.
4. Write a complete new `index_version`; run retrieval + permission evals against it, and check for orphaned eval labels (`doc_id#anchor` that no longer exists); promote the `active_index` pointer only if they pass. Rollback = repoint.

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
| LLM access | LiteLLM -> OpenRouter (dev, bake-off); AWS Bedrock (prod) | pinned model IDs only, never "latest" aliases; OpenRouter provider pinned, no fallbacks; bake-off only considers models on both (ADR-0002) |
| Background jobs | `jobs` table, `SELECT … FOR UPDATE SKIP LOCKED`, one worker process | idempotent jobs (ADR-0003) |
| Cost | `llm_calls` rows, estimated from `model_prices` at call time | per tenant and per conversation (ADR-0005) |
| Local LLM (bake-off only) | Ollama, native macOS | always set `num_ctx` (8192) explicitly |
| Tracing | OpenTelemetry -> Arize Phoenix | |
| UI | Vite + React standalone widget (`widget/`) | must stay embeddable in the CRM later |
| Admin UI | separate Vite + React app (`admin/`) | never shipped in the widget bundle; `admin_role` claim from the JWT |
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
- `LLMClient.complete(messages, *, role) -> Completion`; `StreamingLLMClient.stream(messages, *, role)` yields text deltas then one `Completion`
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
    category: single         # single | multi_hop | unanswerable | out_of_scope | restricted | adversarial
    expected:
      sales_manager@acme: { outcome: answer, required: [campaigns-deal-triggers#connect-a-stage-to-a-campaign] }
      sales_rep@globex:   { outcome: restricted, required: [campaigns-deal-triggers#connect-a-stage-to-a-campaign], missing_modules: [campaigns] }
  ```
  A question a workflow guide answers is labelled with the guide (`single`); `multi_hop` is for questions needing 2+ docs that no guide covers. For labelled categories the per-persona outcome is **derived** (`chatbot.evals.golden`): `answer` if the persona holds every module of every required doc, else `restricted` with exactly the missing modules. `make evals-check` re-derives every stored outcome and fails on drift.
- Generated data is committed with its generator prompt version and seed. Do not regenerate as part of normal runs.

## Database (key tables)

`index_versions` (recipe: parser version, chunker config hash, embed model, status) · `active_index` (alias -> version) · `chunks` (chunk_id, index_version, doc_id, anchor, breadcrumb, content, `modules text[]`, nullable `required_permission`, embedding, generated tsvector, content_hash) · `embedding_cache` (content_hash, embed_model, embedding) · `module_catalogue` · `conversations` / `messages` / `feedback` keyed by trace_id. GIN index on `chunks.modules`.

Added by the admin architecture (full list in `docs/architecture.md` §5): `documents` / `document_versions` (edit history) · `release_documents` · `jobs` · `llm_calls` / `model_prices` · `eval_questions` / `eval_runs` / `eval_results` / `labels` · `audit_log`. **Conversations are server-owned:** a `conversation_id` not owned by the caller (`sub` + `tenant`) gets a 404.

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
  tracing/      # traces + llm_calls cost rows
  jobs/         # Postgres queue + worker (build_release, synthetic evals, e2e evals)
widget/         # embeddable chat widget + dev harness
admin/          # admin app (documents, releases, evals, costs)
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
make start / stop / restart / status / logs   # all dev servers (API :8000, widget :5173, admin :5174) in the background; S=api to pick one
make worker    # job worker (planned)
make widget-dev   # widget + fake-CRM harness on :5173
make admin-dev    # admin app on :5174 (dev sign-in per role)
make admin-types  # regenerate admin API types from the OpenAPI schema
make check     # lint + tests + widget tests + admin tests
```

## Environment constraints (MacBook Air M4, 16 GB)

- Docker runs **only** Postgres and Phoenix (VM capped ~3 GB). Docker on macOS has no GPU access.
- Python service, embedding model, reranker and Ollama run **natively** (MPS / Metal).
- Do not run Ollama during normal development; use OpenRouter. Ollama is for bake-off sessions only.
- Only synthetic docs and synthetic users go to OpenRouter. When real CRM content arrives, development moves to Bedrock (ADR-0002).
- Laptop latency is not representative of production; never use it for self-hosting conclusions.

## Testing and evals

- **Unit tests:** parsers, chunker (snapshot tests on fixtures), filter construction, prompt assembly, citation verification. Mock the LLM.
- **Retrieval evals:** recall@k, **complete recall@k** (all required sections retrieved), MRR, per category. No LLM.
- **Permission suite:** assert `chunk.modules ⊆ persona.allowed` for every retrieved chunk across the persona matrix, plus Hypothesis property tests with random entitlement sets. Zero tolerance.
- **Generation evals (end-to-end):** faithfulness, correctness, refusal accuracy, citation accuracy. **Triggered manually** from the admin app, not on every publish. Judge calibrated against admin hand labels. Report against thresholds and regressions vs baseline, never exact match.
- **Publish gate** = permission suite + retrieval evals + orphaned-label check. No LLM, runs on every publish.
- Eval questions come from admins (UI), synthetic generation (lands as `proposed`; joins the golden set only when accepted), red-team findings, and `evals/golden/*.yaml`.
- Eval harness: retries with backoff and bounded concurrency (provider rate limits).
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

Word/PDF parsing (PDF next, via Docling), module assignment in the admin UI, two-person publish approval, per-tenant budgets/alerts, client-company admins viewing their users' transcripts, docs per CRM release (all clients share one release), image captioning, real CRM entitlement API, CRM embedding, cloud deployment, multilingual UI, voice, iterative retrieval loop, semantic cache, post-hoc groundedness check, self-hosted LLM serving. Interfaces should leave room for these; do not build them.

## ADRs

Record significant decisions in `docs/adr/NNNN-title.md` (context, decision, alternatives, consequences).

Recorded: 0001 Postgres for vector + keyword search · 0002 OpenRouter (dev) then Bedrock (prod) · 0003 Postgres job queue · 0004 content releases, modules controlled in docs · 0005 cost accounting · 0006 admin identity and roles.
Still to record: no orchestration framework, synthetic data strategy, model choice (after bake-off), reranker production compute.
