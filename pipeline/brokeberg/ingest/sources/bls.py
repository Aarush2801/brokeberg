"""BLS latest releases for key series -> `indicators` (source='bls'), keyed by the FRED series ID.

BLS is the primary publisher for these series; storing its values next to FRED's (same series ID,
different `source`) gives the verify pass an independent reference to check FRED against.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy.orm import Session

from brokeberg.config import get_settings
from brokeberg.ingest import http
from brokeberg.ingest.base import Stats
from brokeberg.ingest.store import Observation, upsert_indicators

API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# BLS series ID -> the FRED series ID it is published as (canonical ID for the indicator).
BLS_TO_FRED: dict[str, str] = {
    "CUSR0000SA0": "CPIAUCSL",  # CPI-U all items, SA
    "CUSR0000SA0L1E": "CPILFESL",  # CPI-U less food and energy, SA
    "LNS14000000": "UNRATE",  # unemployment rate, SA
    "CES0000000001": "PAYEMS",  # total nonfarm employment (thousands), SA
    "LNS11300000": "CIVPART",  # labor force participation rate, SA
}


def parse_series(payload: dict[str, Any]) -> list[Observation]:
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS request failed: {payload.get('message')}")
    out = []
    for series in payload["Results"]["series"]:
        fred_id = BLS_TO_FRED.get(series["seriesID"])
        if fred_id is None:
            continue
        for point in series["data"]:
            period = point["period"]
            if not period.startswith("M") or period == "M13":  # M13 = annual average
                continue
            try:
                value = Decimal(point["value"])
            except InvalidOperation:
                continue  # "-" marks a missing value
            out.append(Observation(fred_id, date(int(point["year"]), int(period[1:]), 1), value))
    return out


class BlsLoader:
    source = "bls"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or http.make_client()

    def load(self, session: Session, since: datetime) -> Stats:
        body = {
            "seriesid": list(BLS_TO_FRED),
            "startyear": str(since.year - 1),
            "endyear": str(since.year),
            "registrationkey": get_settings().require("bls_api_key"),
        }
        resp = http.request(self.client, "POST", API_URL, json=body)
        observations = parse_series(resp.json())
        written = upsert_indicators(session, self.source, observations)
        return Stats(
            source=self.source,
            fetched=len(observations),
            inserted=written,
            skipped=len(observations) - written,
        )
