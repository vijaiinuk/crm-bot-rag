# ADR-0006: Admin identity and roles

- Status: accepted
- Date: 2026-11-12

## Context
The admin app changes what chat users can see (uploads, releases, rollbacks) and shows their transcripts and costs. Its authorization must follow the same rule as chat (identity only from a verified token) without letting either kind of token stand in for the other.

## Decision
- Admins authenticate with the **same JWT issuer and validation path** as chat users. An admin token carries `tenant: "ops"` (the configured ops tenant), `role: "ops_admin"` and `admin_role` = `viewer` | `editor` | `publisher`.
- Every `/admin/*` route checks the role from the verified claims, with a minimum role per action:
  - **viewer:** read everything
  - **editor:** upload documents, change the draft release, write, accept and label eval questions
  - **publisher:** publish, confirm widening, roll back, start end-to-end runs
- **Tokens don't cross over.** A client-company token (no `admin_role`, wrong tenant) gets 403 on `/admin/*`. An admin token gets 403 on `/chat`, because `ops_admin@ops` is not a persona, so it fails closed.
- Locally, `data/admins.yaml` lists one admin per role for the dev sign-in and `make token ADMIN=...`; minting is mounted only in `env=local`. In production the claims come from SSO, and the API never reads `admins.yaml`.
- The admin UI hides actions a role can't take. That's a courtesy: the API enforces every check.

## Alternatives
- **A separate admin identity provider or API keys:** a second validation path to secure and audit.
- **Admin role on client-company tokens:** would let a client user's token reach admin routes if a claim were ever mis-issued.

## Consequences
- Client-company admins viewing their own users' transcripts (a later nice-to-have) needs a *tenant-scoped* admin role, whose tenant comes from the token and filters every transcript query. It is not a fourth ops role.
- Audit entries record `sub` from the admin token, so SSO subjects must be stable.
