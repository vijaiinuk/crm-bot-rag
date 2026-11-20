"""Rerank score cache (S2.3.1): a cross-encoder score depends only on the reranker,
the query and the chunk text, so it can be reused across personas and runs.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-20
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE rerank_cache (
            reranker     text NOT NULL,   -- model id @ revision
            query_sha    text NOT NULL,   -- sha256 of the exact query text
            content_hash text NOT NULL,   -- chunks.content_hash (sha256 of embedded text)
            score        double precision NOT NULL CHECK (score >= 0 AND score <= 1),
            created_at   timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (reranker, query_sha, content_hash)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE rerank_cache")
