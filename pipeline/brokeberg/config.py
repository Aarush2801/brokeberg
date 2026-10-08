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

    # Clustering (pass 6). Cosine similarities on bge-large; initial values from the fixture corpus,
    # to be re-tuned on real data. >= t_high (with entity overlap) attaches, < t_low starts a new
    # cluster, the band between gets one LLM tiebreak.
    cluster_t_high: float = 0.85
    cluster_t_low: float = 0.70
    cluster_window_hours: float = 48
    cluster_min_entity_overlap: int = 1
    cluster_knn: int = 10
    # Related events: prior/later cluster heads sharing an entity, centroid cosine >= min_sim.
    # Senate votes share ~100 voters, so the entity filter is weak there; at 0.60 unrelated votes
    # linked on the dev corpus, while true follow-ons (successive cloture votes) scored >= 0.75.
    related_window_days: float = 30
    related_min_sim: float = 0.70

    # Verification (pass 7). Numeric tolerances are absolute: BLS publishes percentages to 1 dp,
    # payroll changes in thousands.
    verify_numeric_tol_pct: float = 0.05
    verify_numeric_tol_thousands: float = 5.0
    # A head none of whose numeric claims match the indicator data keeps this share of confidence.
    verify_numeric_penalty: float = 0.5
    # Both stances need at least this confidence for a reversal to be marked a stance flip.
    verify_stance_min_conf: float = 0.6
    # Heads below this confidence after verification go to the review queue.
    verify_review_confidence: float = 0.5

    # Event -> race linkage: confidence = rating weight x match weight x head confidence.
    race_rating_weight: dict[str, float] = {"tossup": 1.0, "lean": 0.8}
    race_match_weight: dict[str, float] = {"state": 1.0, "politician": 0.9, "federal": 0.6}

    # Feed salience = w1*recency + w2*log(1+sources) + w3*importance + w4*verification
    # + w5*election proximity. All code; the LLM never ranks.
    salience_w1: float = 1.0
    salience_w2: float = 0.5
    salience_w3: float = 0.5
    salience_w4: float = 0.5
    salience_w5: float = 0.75
    salience_half_life_hours: float = 48
    salience_election_tau_days: float = 60
    salience_verification_bonus: dict[str, float] = {
        "fact_checked": 1.0, "corroborated": 0.8, "single_source": 0.3, "unverified": 0.0,
        "contradicted": 0.5,
    }
    # Entity importance when `entities.importance` is unset: by entity type, plus a top prior
    # for the incumbent of a seeded race.
    importance_incumbent: float = 1.0
    importance_by_type: dict[str, float] = {
        "Race": 1.0, "Politician": 0.6, "EconomicIndicator": 0.7, "Policy_Bill": 0.5,
    }
    importance_default: float = 0.4
    feed_window_days: float = 14

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
