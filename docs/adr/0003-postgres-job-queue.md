# ADR-0003: Background jobs on a Postgres queue

- Status: accepted
- Date: 2026-11-12

## Context
The admin app starts long-running work: building a release (chunking, embedding, the eval gate), generating synthetic eval questions, and running end-to-end evals. That work must not run inside an HTTP request, and its progress must be visible in the admin UI. CLAUDE.md rules out Redis for now. The volume is tiny: a few jobs a day.

## Decision
- A `jobs` table in the existing Postgres, claimed with `SELECT … FOR UPDATE SKIP LOCKED`.
- One worker process (`make worker`) from the same Python package. Jobs write `progress jsonb` for the status view.
- Jobs are **idempotent**, keyed on their inputs (for example the release ID), so a crashed or retried job is safe. They retry with backoff, up to a maximum number of attempts.

## Alternatives
- **Celery / RQ / Dramatiq:** need a broker (Redis or RabbitMQ), which means more infrastructure for a few jobs a day.
- **A library on Postgres** (procrastinate, pgqueuer): a reasonable swap if our queue grows features. The interface is kept small so we can switch.
- **FastAPI `BackgroundTasks`:** dies with the API process and has no retries or visibility.
- **AWS SQS / Step Functions:** fits production, but can't run locally without emulation. Revisit for production if needed.

## Consequences
- No new infrastructure; job state is in the same transaction-safe store as the data it changes.
- One worker at a time is enough. Two `build_release` jobs for the same draft must not run concurrently (enforced with a unique key on the active job).
