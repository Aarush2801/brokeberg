import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.db.models import RawItem
from brokeberg.db.seed import seed
from brokeberg.ingest.pipeline import write_raw
from brokeberg.ingest.replay import REPLAY_SINCE, cassette
from brokeberg.ingest.sources.x import (
    MAX_ACCOUNTS,
    RECORDED_ACCOUNTS,
    RECORDED_MAX_RESULTS,
    XConnector,
    load_accounts,
)
from brokeberg.taxonomy import SourceType


def test_account_list_is_capped_and_keyed_by_bioguide() -> None:
    accounts = load_accounts()
    assert 0 < len(accounts) <= MAX_ACCOUNTS
    assert all(len(a.bioguide) == 7 for a in accounts)


def _connector() -> XConnector:
    return XConnector(max_accounts=RECORDED_ACCOUNTS, max_results=RECORDED_MAX_RESULTS)


def test_x_posts_map_to_bioguide_and_report_reads(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(db_session)
    conn = _connector()
    with cassette("x"):
        records = list(conn.fetch(db_session, REPLAY_SINCE))
    assert conn.reads == len(records) <= RECORDED_ACCOUNTS * RECORDED_MAX_RESULTS
    assert f"read count this pull = {conn.reads}" in capsys.readouterr().out

    first = write_raw(db_session, conn, records)
    assert first.inserted == len(records)
    for r in records:
        assert r.url.startswith("https://x.com/") and r.entity_ids[0].startswith("bioguide:")

    again_conn = _connector()
    with cassette("x"):
        again = write_raw(db_session, again_conn, again_conn.fetch(db_session, REPLAY_SINCE))
    assert again.inserted == 0
    rows = db_session.scalars(select(RawItem).where(RawItem.source == "x")).all()
    assert len(rows) == len(records)
    assert {r.source_type for r in rows} <= {SourceType.SOCIAL_POST}
