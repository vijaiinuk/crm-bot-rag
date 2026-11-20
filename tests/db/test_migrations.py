"""S1.4.1: Alembic baseline. The first tests need no database; the `db` ones do."""

import io

import psycopg
import pytest
from alembic import command
from alembic.script import ScriptDirectory

from chatbot.db import alembic_config
from tests.conftest import TEST_DATABASE_URL


def test_migrations_form_one_linear_history() -> None:
    scripts = ScriptDirectory.from_config(alembic_config())
    assert scripts.get_heads() == ["0003"]
    revisions = list(scripts.walk_revisions())
    assert revisions[-1].down_revision is None
    assert all(not r.is_merge_point for r in revisions), "no merge migrations"


def test_baseline_sql_enables_pgvector_without_a_database() -> None:
    """Offline mode runs env.py and the migration, printing SQL instead of connecting."""
    cfg = alembic_config("postgresql+psycopg://nobody@nowhere/none")
    cfg.output_buffer = io.StringIO()
    command.upgrade(cfg, "head", sql=True)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in cfg.output_buffer.getvalue()


@pytest.mark.db
def test_pgvector_is_installed_and_computes_distances(pg_url: str) -> None:
    with psycopg.connect(pg_url) as conn:
        version = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        assert version.fetchone() is not None
        row = conn.execute("SELECT '[1,0]'::vector <=> '[0,1]'::vector").fetchone()
        assert row is not None and row[0] == pytest.approx(1.0)  # cosine distance


@pytest.mark.db
def test_migrations_go_down_and_back_up(pg_url: str) -> None:
    cfg = alembic_config(TEST_DATABASE_URL)
    command.downgrade(cfg, "base")
    with psycopg.connect(pg_url) as conn:
        gone = conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone()
        assert gone is None
    command.upgrade(cfg, "head")
    with psycopg.connect(pg_url) as conn:
        back = conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone()
        assert back is not None
