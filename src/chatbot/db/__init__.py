"""Database: Alembic migrations (SQLAlchemy is used only there; runtime code uses
psycopg 3 with hand-written SQL, so the module filter stays visible)."""

from pathlib import Path

from alembic.config import Config

MIGRATIONS = Path(__file__).parent / "migrations"


def alembic_config(url: str | None = None) -> Config:
    """Alembic config for code and tests. `url` overrides Settings.database_url."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    if url is not None:
        cfg.attributes["url"] = url
    return cfg
