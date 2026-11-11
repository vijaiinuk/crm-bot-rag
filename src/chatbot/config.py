from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHATBOT_", env_file=".env", extra="ignore")

    env: Literal["local", "test", "prod"] = "local"

    jwt_issuer: str = "http://localhost:8000"
    jwt_audience: str = "crm-help-bot"
    jwks_url: str = "http://localhost:8000/.well-known/jwks.json"
    jwks_cache_ttl_s: float = 300.0
    jwt_leeway_s: int = 30

    # Browser origins allowed to call the API (the widget's host page). Empty = none.
    cors_origins: list[str] = []

    personas_path: Path = Path("data/personas.yaml")
    catalogue_path: Path = Path("data/module_catalogue.yaml")
    # Pause between streamed mock tokens, so streaming is visible in the UI.
    mock_token_delay_s: float = 0.03
    # Local signing keys; only read when env == "local".
    keys_dir: Path = Path(".local/keys")
