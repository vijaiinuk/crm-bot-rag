# ADR-0002: OpenRouter in development, Bedrock in production

- Status: accepted
- Date: 2026-11-12
- Supersedes: "LiteLLM → AWS Bedrock" in the CLAUDE.md stack table (for development only)

## Context
We want to start with the smallest workable model and grow only when evals demand it. That needs a cheap way to compare many models from different vendors, and the LLM judge must come from a different vendor than the generator. Production runs on AWS. Development uses synthetic docs and synthetic users only.

## Decision
- All LLM calls go through **LiteLLM**; the provider is configuration (`config/models.yaml`).
- **Development and bake-off: OpenRouter.** One API key for every vendor, so the bake-off and a different-vendor judge are trivial.
- **Production: AWS Bedrock.** Data stays in our AWS account with no third-party processor, and the region can be pinned.
- So that bake-off results carry over to production:
  - The bake-off **only considers models available on both OpenRouter and Bedrock**.
  - OpenRouter requests **pin the provider** to the model vendor's own endpoint and **disable fallbacks**, so a single model ID isn't silently served by different backends.
  - Model IDs are pinned versions, never "latest" aliases.
- Cost is **estimated** from `tokens × model_prices`, the same way for both providers (see ADR-0005). We don't rely on OpenRouter's reported cost.

## Alternatives
- **Bedrock from day one:** no switch later, but slower model exploration and low default quotas on new accounts.
- **OpenRouter in production:** adds a third-party processor for client users' questions. That needs legal review and a data processing agreement, and gains little once the model is chosen.
- **Direct vendor APIs:** a separate key, SDK quirks and billing per vendor.

## Consequences
- **No real CRM content or real user data goes to OpenRouter.** Synthetic data needs no agreement. Real data does, for three reasons:
  - User questions can contain personal data (names, emails of the client's own customers). Under GDPR-style rules, whoever processes that data on our behalf needs a data processing agreement, and it should usually be named as a sub-processor in our client contracts.
  - OpenRouter forwards each request to an underlying model vendor, which is a further sub-processor with its own retention rules.
  - The CRM's own documentation is confidential company material.
- **When real docs arrive, the default is to move development to Bedrock** rather than put OpenRouter under contract. Bedrock is already covered by the AWS agreements that production needs.
- Prompt caching and structured-output support differ between OpenRouter backends and Bedrock. The bake-off must be re-checked on Bedrock (a short smoke eval) before the production switch.
- Embeddings and reranking stay local (`bge-m3`, `bge-reranker-v2-m3`) whatever the LLM provider.
