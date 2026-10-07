from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.db.models import RawItem
from brokeberg.db.seed import seed
from brokeberg.ingest.base import RawRecord, Stats
from brokeberg.ingest.pipeline import write_raw
from brokeberg.ingest.replay import REPLAY_SINCE, cassette
from brokeberg.ingest.sources.congress import (
    CongressConnector,
    SenateVotesConnector,
    congress_for,
)
from brokeberg.taxonomy import SourceType


def test_congress_for_year() -> None:
    assert congress_for(2025) == congress_for(2026) == 119
    assert congress_for(2027) == 120


def _run(db_session: Session) -> tuple[list[RawRecord], Stats]:
    conn = CongressConnector()
    with cassette("congress"):
        records = list(conn.fetch(db_session, REPLAY_SINCE))
    return records, write_raw(db_session, conn, records)


def test_bills_map_sponsors_to_bioguide_and_dedup(db_session: Session) -> None:
    seed(db_session)
    records, stats = _run(db_session)
    assert records, "cassette should contain recently updated Senate bills"
    for r in records:
        assert r.url.startswith("https://www.congress.gov/bill/119th-congress/senate-bill/")
        assert r.raw_payload["kind"] == "bill" and r.text.startswith("S. ")
    # Every sponsor of a Senate bill is a sitting senator, so all resolve by exact bioguide.
    assert all(r.entity_ids and all(e.startswith("bioguide:") for e in r.entity_ids)
               for r in records)
    assert not any(r.unresolved for r in records)

    _, again = _run(db_session)
    assert again.inserted == 0
    rows = db_session.scalars(select(RawItem).where(RawItem.source == "congress")).all()
    assert len(rows) == len(records)
    assert {r.source_type for r in rows} == {SourceType.GOVERNMENT_PRIMARY}


def test_senate_votes_map_members_to_bioguide_and_dedup(db_session: Session) -> None:
    seed(db_session)
    conn = SenateVotesConnector()
    with cassette("senate_votes"):
        records = list(conn.fetch(db_session, REPLAY_SINCE))
    assert records, "cassette should contain roll calls since the recording date"
    for r in records:
        assert r.url.startswith("https://voteview.com/rollcall/RS119")
        assert r.raw_payload["official_url"].startswith("https://www.senate.gov/legislative/LIS/")
        assert r.event_time is not None and r.event_time >= REPLAY_SINCE
        # Sitting senators all resolve exactly; nobody is minted.
        assert len(r.entity_ids) >= 95 and all(e.startswith("bioguide:") for e in r.entity_ids)

    first = write_raw(db_session, conn, records)
    assert first.inserted == len(records)
    with cassette("senate_votes"):
        again = write_raw(db_session, conn, conn.fetch(db_session, REPLAY_SINCE))
    assert again.inserted == 0
