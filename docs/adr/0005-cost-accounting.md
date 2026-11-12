# ADR-0005: Estimated LLM cost per client company and per chat session

- Status: accepted
- Date: 2026-11-12

## Context
Admins need to see LLM cost broken down by client company and, where possible, by chat session. Providers differ: OpenRouter reports cost per request, Bedrock doesn't. Message text has a short retention period (PII); cost history needs to last much longer.

## Decision
- Every LLM call writes one `llm_calls` row: `trace_id`, `conversation_id`, `tenant`, `bucket` (chat / eval / ingest), `stage`, `model_id`, `provider`, token counts (including cached input), `price_id` and `cost_usd`, plus latency.
- Cost is **estimated** as `tokens × model_prices` at call time. Prices are versioned (`valid_from`), so historic costs never change.
- `llm_calls` holds **no message text** and is kept long-term. The messages themselves expire after 30 days.
- **Conversations are created and owned by the server.** A `conversation_id` not owned by the caller (`sub` + `tenant`) gets a 404. Without this, session costs and history could be attributed to, or read by, the wrong user.
- Eval, judge and synthetic-generation calls are booked to `bucket = eval / ingest`, never to a client company.
- Local embedding and reranking are infrastructure cost, not counted per request.

## Alternatives
- **Provider-reported cost:** only OpenRouter has it, so the method would change on the move to Bedrock.
- **Costs from Phoenix:** Phoenix is an engineering tool, and the cost data would follow its retention and schema.
- **AWS Cost Explorer only:** no per-tenant or per-session breakdown.

## Consequences
- Estimates drift from the real bill if the price table is stale. The monthly total is compared with the provider invoice as a sanity check.
- Per-tenant budgets and alerts can be added later on the same table.
