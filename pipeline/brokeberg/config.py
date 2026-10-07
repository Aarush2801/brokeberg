"""Settings loaded from the repo-root `.env`.

Nothing here fails at import. Components call `settings.require("x")` when they actually need a
key, so a missing FRED key never breaks, say, the embedding path.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class MissingConfigError(RuntimeError):
    """A component needed a setting that is not configured."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+psycopg://brokeberg:brokeberg@localhost:5432/brokeberg"

    # LLM
    llm_provider: Literal["anthropic", "bedrock"] = "anthropic"
    llm_model: str = "claude-sonnet-5-5"
    # Cheap tier for high-volume passes (gate, event core, classify).
    llm_model_cheap: str = "claude-haiku-4-5"
    anthropic_api_key: str | None = None

    # Embeddings
    embed_provider: Literal["local", "bedrock"] = "local"
    embed_model: str = "BAAI/bge-large-en-v1.5"
    embed_dim: int = 1024

    # AWS
    aws_region: str | None = None
    s3_raw_bucket: str | None = None

    # Source keys
    congress_api_key: str | None = None
    fred_api_key: str | None = None
    bls_api_key: str | None = None
    data_gov_api_key: str | None = None
    census_api_key: str | None = None
    x_bearer_token: str | None = None

    def require(self, name: str) -> str:
        """Return a setting's value, raising if it is unset or empty."""
        value = getattr(self, name, None)
        if value is None or value == "":
            raise MissingConfigError(
                f"{name.upper()} is not set. Add it to {REPO_ROOT / '.env'} or the environment."
            )
        return str(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()
