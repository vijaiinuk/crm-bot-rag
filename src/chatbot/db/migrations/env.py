"""Alembic environment. Migrations are hand-written SQL: no models, no autogenerate."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from chatbot.config import Settings

if context.config.config_file_name:  # the CLI; tests pass no ini and keep their logging
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)


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
