from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from brokeberg.db.models import Entity, Event, Race
from brokeberg.db.seed import seed
from brokeberg.taxonomy import EventType


def _counts(session: Session) -> tuple[int, int]:
    entities = session.scalar(select(func.count()).select_from(Entity)) or 0
    races = session.scalar(select(func.count()).select_from(Race)) or 0
    return entities, races


def test_seed_counts(db_session: Session) -> None:
    counts = seed(db_session)
    assert counts == {
        "Politician": 100,
        "Jurisdiction": 51,
        "Race": 10,
        "EconomicIndicator": 22,
        "races": 10,
    }


def test_seed_is_idempotent(db_session: Session) -> None:
    seed(db_session)
    first = _counts(db_session)
    versions = _row_versions(db_session)
    with db_session.begin_nested():  # own subtransaction id, so any rewrite changes xmin
        seed(db_session)
    assert _counts(db_session) == first
    assert _row_versions(db_session) == versions  # unchanged rows are not rewritten


def _row_versions(session: Session) -> list[str]:
    return list(
        session.scalars(
            text("SELECT xmin::text FROM entities UNION ALL SELECT xmin::text FROM races")
        )
    )


def test_races_have_no_unsourced_ratings(db_session: Session) -> None:
    seed(db_session)
    races = db_session.scalars(select(Race)).all()
    assert all(r.rating is None and r.fec_candidate_ids == [] for r in races)
    assert "AZ-SEN-2026" not in {r.id for r in races}


def _event(session: Session) -> int:
    event = Event(
        event_type=EventType.STATEMENT,
        headline="x",
        event_time=datetime(2026, 10, 1, tzinfo=UTC),
        confidence=0.9,
    )
    session.add(event)
    session.flush()
    return event.id


def test_provenance_requires_a_span(db_session: Session) -> None:
    event_id = _event(db_session)
    with pytest.raises(IntegrityError, match="ck_event_sources_span_non_empty"):
        db_session.execute(
            text(
                "INSERT INTO event_sources (event_id, url, span, trust_tier) "
                "VALUES (:e, 'https://example.gov', '   ', 'T1')"
            ),
            {"e": event_id},
        )


def test_no_causal_edges_in_db(db_session: Session) -> None:
    seed(db_session)
    a, b = db_session.scalars(select(Entity.id).limit(2)).all()
    with pytest.raises(IntegrityError, match="ck_edges_edge_type"):
        db_session.execute(
            text(
                "INSERT INTO edges (src_entity, relation, dst_entity, confidence) "
                "VALUES (:a, 'CAUSES', :b, 0.5)"
            ),
            {"a": a, "b": b},
        )


def test_raw_item_content_hash_is_unique(db_session: Session) -> None:
    insert = text(
        "INSERT INTO raw_items (source, source_type, content_hash, url, payload_jsonb) "
        "VALUES ('fred', 'data_release', 'abc', 'https://x', '{}')"
    )
    db_session.execute(insert)
    with pytest.raises(IntegrityError, match="uq_raw_items_content_hash"):
        db_session.execute(insert)
