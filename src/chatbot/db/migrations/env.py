"""Alembic environment. Migrations are hand-written SQL: no models, no autogenerate."""

from alembic import context
from sqlalchemy import create_engine, pool

from chatbot.config import Settings


def _url() -> str:
    override = context.config.attributes.get("url")
    return str(override) if override else Settings().database_url.get_secret_value()


def run_offline() -> None:
    context.configure(url=_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
