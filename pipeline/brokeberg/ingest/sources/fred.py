"""FRED observations for the seeded series -> `indicators` (source='fred').

Structured data, so no raw_items. Pulls a lookback window before `since` so that revisions to
recent observations are picked up; the upsert only writes values that changed.
"""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy.orm import Session

from brokeberg.config import get_settings
from brokeberg.db.seed_data.fred_series import SERIES
from brokeberg.ids import fred as fred_ids
from brokeberg.ingest import http
from brokeberg.ingest.base import Stats
from brokeberg.ingest.store import Observation, upsert_indicators

OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
# Window before `since`, per series frequency, wide enough to include the latest release.
LOOKBACK: dict[str, timedelta] = {
    "daily": timedelta(days=60),
    "weekly": timedelta(days=90),
    "monthly": timedelta(days=180),
    "quarterly": timedelta(days=400),
    "annual": timedelta(days=800),
}


def parse_observations(series_id: str, payload: dict[str, Any]) -> list[Observation]:
    out = []
    for obs in payload.get("observations", []):
        try:
            value = Decimal(obs["value"])
        except (InvalidOperation, KeyError):
            continue  # FRED uses "." for missing
        out.append(Observation(series_id, datetime.fromisoformat(obs["date"]).date(), value))
    return out


class FredLoader:
    source = "fred"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or http.make_client()

    def load(self, session: Session, since: datetime) -> Stats:
        key = get_settings().require("fred_api_key")
        stats = Stats(source=self.source)
        for seed in SERIES:
            series_id = fred_ids.normalize(seed.series_id)
            if series_id is None:
                continue
            resp = http.get(
                self.client,
                OBSERVATIONS_URL,
                params={
                    "series_id": series_id,
                    "observation_start": (since - LOOKBACK[seed.frequency]).date().isoformat(),
                    "file_type": "json",
                    "api_key": key,
                },
            )
            observations = parse_observations(series_id, resp.json())
            written = upsert_indicators(session, self.source, observations)
            stats.fetched += len(observations)
            stats.inserted += written
            stats.skipped += len(observations) - written
        return stats
