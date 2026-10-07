import pytest
from pydantic import ValidationError
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
    Account,
    XConnector,
    load_accounts,
    post_record,
)
from brokeberg.taxonomy import SourceType


def test_account_list_is_capped_and_members_keyed_by_bioguide() -> None:
    accounts = load_accounts()
    assert 0 < len(accounts) <= MAX_ACCOUNTS
    members = [a for a in accounts if a.kind == "member"]
    assert members and all(a.bioguide and len(a.bioguide) == 7 for a in members)
    assert {a.handle for a in accounts if a.kind == "media"} == {"FT", "nytimes"}


def test_member_account_requires_bioguide() -> None:
    with pytest.raises(ValidationError):
        Account(handle="someone", user_id="1")


def test_media_post_links_no_entity_and_member_payload_unchanged(db_session: Session) -> None:
    tweet = {"id": "1", "text": "Fed holds rates", "created_at": "2026-10-01T12:00:00.000Z"}
    media = post_record(db_session, Account(handle="FT", user_id="18949452", kind="media"), tweet)
    assert (media.entity_ids, media.unresolved) == ([], [])
    assert media.raw_payload["author"] == {"handle": "FT", "user_id": "18949452", "kind": "media"}

    member = Account(handle="SenOssoff", user_id="1356714265894408196", bioguide="O000174")
    # Same author shape as before `kind` existed, so stored posts keep their content hashes.
    assert post_record(db_session, member, tweet).raw_payload["author"] == {
        "handle": "SenOssoff", "user_id": "1356714265894408196", "bioguide": "O000174"
    }


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
