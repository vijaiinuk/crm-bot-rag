"""Index versions, chunks, embedding cache, module catalogue (S2.1.3).

Exact vector search on purpose: there is deliberately NO HNSW/IVF index on
chunks.embedding (CLAUDE.md, ~4k chunks). A test asserts none exists.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE module_catalogue (
            module       text PRIMARY KEY,
            display_name text NOT NULL,
            description  text NOT NULL,
            updated_at   timestamptz NOT NULL DEFAULT now()
        );

        -- One row per build. A release, in the admin architecture's terms.
        CREATE TABLE index_versions (
            index_version bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            status        text NOT NULL DEFAULT 'building'
                CHECK (status IN ('building', 'gate', 'live', 'superseded', 'failed')),
            recipe        jsonb NOT NULL,     -- parser/chunker/embedder versions and hashes
            corpus_sha    text,               -- sha256 over every doc's sha256, in order
            doc_count     int,
            chunk_count   int,
            embedded      int,                -- chunks embedded in this build
            reused        int,                -- chunks served from embedding_cache
            ungated       boolean NOT NULL DEFAULT false,  -- promoted without the S2.4.1 gate
            error         text,
            created_at    timestamptz NOT NULL DEFAULT now(),
            finished_at   timestamptz,
            promoted_at   timestamptz
        );

        CREATE TABLE active_index (
            alias         text PRIMARY KEY,
            index_version bigint NOT NULL REFERENCES index_versions,
            updated_at    timestamptz NOT NULL DEFAULT now()
        );

        -- History of every repoint; rollback = promote the version the last one replaced.
        CREATE TABLE index_promotions (
            id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            alias        text NOT NULL,
            from_version bigint REFERENCES index_versions,
            to_version   bigint NOT NULL REFERENCES index_versions,
            reason       text NOT NULL CHECK (reason IN ('promote', 'rollback')),
            at           timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE embedding_cache (
            content_hash text NOT NULL,
            embed_model  text NOT NULL,       -- model id @ revision
            embedding    vector(1024) NOT NULL,
            created_at   timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (content_hash, embed_model)
        );

        CREATE TABLE chunks (
            index_version       bigint NOT NULL REFERENCES index_versions ON DELETE CASCADE,
            chunk_id            text NOT NULL,
            doc_id              text NOT NULL,
            doc_version         int NOT NULL,
            anchor              text NOT NULL,
            parent_anchor       text,
            part                int NOT NULL,
            breadcrumb          text NOT NULL,
            content             text NOT NULL,
            -- Rule 4, fail closed: a chunk with no modules can never be stored.
            modules             text[] NOT NULL CHECK (cardinality(modules) > 0),
            required_permission text,
            token_count         int NOT NULL,
            oversized           boolean NOT NULL,
            content_hash        text NOT NULL,
            embedding           vector(1024) NOT NULL,
            tsv tsvector GENERATED ALWAYS AS (
                to_tsvector('english', breadcrumb || ' ' || content)
            ) STORED,
            PRIMARY KEY (index_version, chunk_id)
        );
        CREATE INDEX chunks_modules_gin ON chunks USING gin (modules);
        CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE chunks;
        DROP TABLE embedding_cache;
        DROP TABLE index_promotions;
        DROP TABLE active_index;
        DROP TABLE index_versions;
        DROP TABLE module_catalogue;
        """
    )
