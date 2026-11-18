from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHATBOT_", env_file=".env", extra="ignore")

    env: Literal["local", "test", "prod"] = "local"

    jwt_issuer: str = "http://localhost:8000"
    jwt_audience: str = "crm-help-bot"
    jwks_url: str = "http://localhost:8000/.well-known/jwks.json"
    jwks_cache_ttl_s: float = 300.0
    jwt_leeway_s: int = 30

    # Admin tokens carry this tenant plus an `admin_role` claim.
    admin_tenant: str = "ops"
    admins_path: Path = Path("data/admins.yaml")

    # Browser origins allowed to call the API (the widget's host page). Empty = none.
    cors_origins: list[str] = []

    personas_path: Path = Path("data/personas.yaml")
    catalogue_path: Path = Path("data/module_catalogue.yaml")
    # Pause between streamed mock tokens, so streaming is visible in the UI.
    mock_token_delay_s: float = 0.03
    # Pause per simulated build stage in the admin mock, so progress is visible.
    mock_job_step_s: float = 0.8
    # Model IDs, providers and routing (never hardcode model IDs).
    models_path: Path = Path("config/models.yaml")
    # OpenRouter key for development (ADR-0002). Read as OPENROUTER_API_KEY, the
    # name every OpenRouter tool uses, and passed to LiteLLM explicitly rather
    # than through the process environment. Synthetic data only.
    openrouter_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENROUTER_API_KEY", "CHATBOT_OPENROUTER_API_KEY"),
    )
    # Postgres (S1.4.1). The default is the local compose container (localhost
    # only, not a secret); anywhere else, set CHATBOT_DATABASE_URL.
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://chatbot:chatbot@localhost:5432/chatbot"
    )
    # Local signing keys; only read when env == "local".
    keys_dir: Path = Path(".local/keys")
