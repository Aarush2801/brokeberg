"""OpenFEC candidate totals for each target race.

Writes three things, all idempotently:
- `races.fec_candidate_ids` and `races.meta["finance"]` (structured, overwritten when changed);
- one `raw_items` row per candidate finance snapshot (data_release). The payload is the filed
  totals, so the content hash changes exactly when a new filing changes the numbers.

Incumbents resolve to their bioguide node (FEC IDs live in its aliases/meta); challengers keep
their FEC canonical ID, and no node is minted for them here.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.config import get_settings
from brokeberg.db.models import Race
from brokeberg.ids import fec as fec_ids
from brokeberg.ids import fips
from brokeberg.ids.canonical import Namespace, is_valid, make
from brokeberg.ingest import http
from brokeberg.ingest.base import RawRecord, Stats
from brokeberg.ingest.pipeline import write_raw
from brokeberg.taxonomy import RaceType, SourceType

TOTALS_URL = "https://api.open.fec.gov/v1/candidates/totals/"
CANDIDATE_URL = "https://www.fec.gov/data/candidate/{}/?cycle={}"
ELECTION_URL = "https://www.fec.gov/data/elections/senate/{}/{}/"
PAYLOAD_FIELDS = (
    "candidate_id", "name", "party", "incumbent_challenge", "candidate_status", "receipts",
    "disbursements", "cash_on_hand_end_period", "debts_owed_by_committee",
    "coverage_start_date", "coverage_end_date", "last_file_date",
)


def _money(value: Any) -> str:
    return f"${Decimal(str(value or 0)):,.0f}"


def candidate_record(session: Session, race: Race, row: dict[str, Any]) -> RawRecord:
    cid = row["candidate_id"]
    entity = fec_ids.by_fec_id(session, cid)
    entity_ids = [make(Namespace.RACE, race.id)]
    entity_ids.append(entity.canonical_id if entity else make(Namespace.FEC, cid))
    status = row.get("incumbent_challenge_full") or row.get("incumbent_challenge") or ""
    end = row.get("coverage_end_date")
    text = (
        f"{row['name']} ({row.get('party')}, {status}) in {race.id}: receipts "
        f"{_money(row.get('receipts'))}, disbursements {_money(row.get('disbursements'))}, "
        f"cash on hand {_money(row.get('cash_on_hand_end_period'))}"
        + (f" through {end}." if end else ".")
    )
    return RawRecord(
        url=CANDIDATE_URL.format(cid, race.cycle),
        text=text,
        event_time=datetime.fromisoformat(end).replace(tzinfo=UTC) if end else None,
        raw_payload={"race_id": race.id, **{k: row.get(k) for k in PAYLOAD_FIELDS}},
        entity_ids=entity_ids,
    )


def finance_meta(race: Race, rows: list[dict[str, Any]]) -> dict[str, Any]:
    state = fips.BY_FIPS[race.state_fips]
    ends = [r["coverage_end_date"] for r in rows if r.get("coverage_end_date")]
    return {
        "asof": max(ends) if ends else None,
        "source_url": ELECTION_URL.format(state.abbrev, race.cycle),
        "candidates": {
            r["candidate_id"]: {
                k: r.get(k)
                for k in ("name", "party", "incumbent_challenge", "receipts", "disbursements",
                          "cash_on_hand_end_period", "coverage_end_date")
            }
            for r in rows
        },
    }


class FecLoader:
    source = "fec"
    source_type = SourceType.DATA_RELEASE

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or http.make_client()

    def _totals(self, race: Race) -> list[dict[str, Any]]:
        state = fips.BY_FIPS[race.state_fips]
        resp = http.get(
            self.client,
            TOTALS_URL,
            params={
                "office": "S",
                "state": state.abbrev,
                "election_year": race.cycle,
                "election_full": "true",
                "per_page": 100,
                "sort": "-receipts",
                "api_key": get_settings().require("data_gov_api_key"),
            },
        )
        rows = resp.json().get("results", [])
        # Paper candidates with no money add noise; a valid ID is required for the graph.
        return [
            r for r in rows
            if is_valid(Namespace.FEC, r.get("candidate_id", "")) and (r.get("receipts") or 0) > 0
        ]

    def _records(self, session: Session, races: list[Race]) -> Iterator[RawRecord]:
        for race in races:
            rows = self._totals(race)
            ids = sorted(r["candidate_id"] for r in rows)
            meta = {**race.meta, "finance": finance_meta(race, rows)}
            if race.fec_candidate_ids != ids:
                race.fec_candidate_ids = ids
            if race.meta != meta:
                race.meta = meta
            for row in rows:
                yield candidate_record(session, race, row)

    def load(self, session: Session, since: datetime) -> Stats:
        races = list(
            session.scalars(
                select(Race)
                .where(Race.office == RaceType.SENATE, Race.cycle >= since.year)
                .order_by(Race.id)
            )
        )
        stats = write_raw(session, self, self._records(session, races))
        session.flush()
        stats.note = f"races={len(races)}"
        return stats
