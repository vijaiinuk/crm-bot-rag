# ADR-0004: Content releases; modules controlled in the docs

- Status: accepted
- Date: 2026-11-12

## Context
Admins upload versioned docs and publish them from an admin app. A doc's modules are its permission boundary (rules 4 and 5), so any change to what's live is an access-control change. All client companies run the same CRM release (confirmed 2026-11-12).

## Decision
- **Formats:** markdown with the existing frontmatter contract only. PDF and Word are deferred to a later release (PDF via Docling, which is MIT licensed; not PyMuPDF, which is AGPL).
- **Modules come only from the doc's frontmatter.** The admin UI has no module assignment in the MVP.
- **Edit history:** each upload creates an immutable `document_versions` row. Only the version in the live release is retrievable.
- **Releases:** publishing builds a complete, immutable index version from a chosen set of document versions. It's promoted only after an automatic, LLM-free gate:
  1. the permission suite (zero tolerance)
  2. no retrieval-eval regression against the live release
  3. no orphaned eval labels (`doc_id#anchor` that no longer exists)
  4. **access widening** (a doc's modules changed to something more visible) requires explicit publisher confirmation, recorded in `audit_log`
- **Rollback** repoints `active_index` to the previous release.
- Validation runs at upload, so bad docs are rejected early. Building a release stays all-or-nothing (rule 4).

## Alternatives
- **Live edits to chunks** (embed on upload, visible immediately): bypasses the permission gate and makes rollback hard.
- **Module assignment in the admin UI:** splits the source of truth between file and database. Deferred.
- **Upload-date filter for freshness:** an upload date doesn't measure how current the content is. Replaced by retiring docs and a staleness report.

## Consequences
- Every content change, even a typo fix, goes through publish and the gate. At ~100 docs this takes seconds, thanks to the embedding cache.
- If clients turn out to be on different CRM releases, docs need a `release` dimension resolved from the tenant, like modules. This ADR would then be superseded.
