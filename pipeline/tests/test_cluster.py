from datetime import timedelta
from typing import Any

import pytest
from cluster_corpus import (
    CPI_BLS,
    CPI_NEWS,
    CPI_REACTION,
    NOMINATION,
    SULLIVAN,
    T0,
    FakeEmbedder,
    add_member,
    unit_vec,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brokeberg.cluster import embed_events
from brokeberg.cluster.cluster import Candidate, Decision, SameEvent, cluster_pending, decide
from brokeberg.cluster.embed_events import embed_pending
from brokeberg.config import get_settings
from brokeberg.db.models import Event, EventEmbedding, ReviewQueue


@pytest.fixture
def fake_embed(monkeypatch: pytest.MonkeyPatch) -> FakeEmbedder:
    fake = FakeEmbedder()
    monkeypatch.setattr(embed_events, "embed", fake)
    return fake


@pytest.fixture
def cpi_corpus(seeded_db: Session, fake_embed: FakeEmbedder) -> dict[str, Event]:
    """3 CPI reports (cosines with the first: 1.0, 0.95, 0.90) + an orthogonal nomination."""
    fake_embed.set(CPI_BLS.headline, unit_vec(1.0, 9))
    fake_embed.set(CPI_NEWS.headline, unit_vec(0.95, 1))
    fake_embed.set(CPI_REACTION.headline, unit_vec(0.90, 2))
    fake_embed.set(NOMINATION.headline, unit_vec(0.0, 5))
    return {
        "bls": add_member(seeded_db, CPI_BLS),
        "news": add_member(seeded_db, CPI_NEWS),
        "reaction": add_member(seeded_db, CPI_REACTION),
        "nomination": add_member(seeded_db, NOMINATION),
    }


def _heads(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Event).where(Event.id == Event.cluster_id))


@pytest.mark.parametrize(
    ("sim", "expected"),
    [
        (None, Decision.NEW),
        (0.0, Decision.NEW),
        (0.6999, Decision.NEW),
        (0.70, Decision.TIEBREAK),
        (0.8499, Decision.TIEBREAK),
        (0.85, Decision.ATTACH),
        (1.0, Decision.ATTACH),
    ],
)
def test_decide_bands(sim: float | None, expected: Decision) -> None:
    top = None if sim is None else Candidate(cluster_id=1, similarity=sim, overlap=1)
    assert decide(top, get_settings()) == expected


def test_thresholds_come_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUSTER_T_HIGH", "0.99")
    get_settings.cache_clear()
    assert decide(Candidate(1, 0.95, 1), get_settings()) == Decision.TIEBREAK


def test_cpi_reports_form_one_cluster(
    seeded_db: Session, cpi_corpus: dict[str, Event], fake_llm: Any
) -> None:
    assert embed_pending(seeded_db) == 4
    stats = cluster_pending(seeded_db)

    assert (stats.new, stats.attached, stats.tiebreaks) == (2, 2, 0)
    bls, news, reaction, nom = (cpi_corpus[k] for k in ("bls", "news", "reaction", "nomination"))
    assert bls.cluster_id == news.cluster_id == reaction.cluster_id
    assert nom.cluster_id not in (None, bls.cluster_id)
    assert _heads(seeded_db) == 2
    # Heads are never embedded; similarity runs over members only.
    assert seeded_db.get(EventEmbedding, bls.cluster_id) is None
    assert fake_llm.calls == []


def test_rerun_is_idempotent(
    seeded_db: Session, cpi_corpus: dict[str, Event], fake_embed: FakeEmbedder
) -> None:
    embed_pending(seeded_db)
    cluster_pending(seeded_db)
    before = {k: e.cluster_id for k, e in cpi_corpus.items()}
    embed_calls = fake_embed.calls

    assert embed_pending(seeded_db) == 0
    stats = cluster_pending(seeded_db)

    assert (stats.new, stats.attached) == (0, 0)
    assert fake_embed.calls == embed_calls
    assert {k: e.cluster_id for k, e in cpi_corpus.items()} == before
    assert _heads(seeded_db) == 2


@pytest.mark.parametrize("same", [True, False])
def test_ambiguous_band_gets_exactly_one_tiebreak(
    seeded_db: Session, cpi_corpus: dict[str, Event], fake_embed: FakeEmbedder,
    fake_llm: Any, same: bool,
) -> None:
    embed_pending(seeded_db)
    cluster_pending(seeded_db)
    fake_llm.set(
        SameEvent, SameEvent(same=same, reason="same August CPI release", confidence=0.9)
    )
    fake_embed.set("CPI follow-up", unit_vec(0.78, 7))  # in (t_low, t_high)
    late = add_member(seeded_db, CPI_NEWS, headline="CPI follow-up", url="https://ex.com/1")
    embed_pending(seeded_db)

    stats = cluster_pending(seeded_db)

    assert fake_llm.schemas_called() == [SameEvent]
    assert stats.tiebreaks == 1
    assert (late.cluster_id == cpi_corpus["bls"].cluster_id) is same


def test_low_confidence_tiebreak_splits_and_goes_to_review(
    seeded_db: Session, cpi_corpus: dict[str, Event], fake_embed: FakeEmbedder,
    fake_llm: Any,
) -> None:
    embed_pending(seeded_db)
    cluster_pending(seeded_db)
    fake_llm.set(SameEvent, SameEvent(same=True, reason="unsure", confidence=0.3))
    fake_embed.set("CPI maybe", unit_vec(0.78, 7))
    late = add_member(seeded_db, CPI_NEWS, headline="CPI maybe", url="https://ex.com/2")
    embed_pending(seeded_db)

    cluster_pending(seeded_db)

    assert late.cluster_id not in (None, cpi_corpus["bls"].cluster_id)
    review = seeded_db.scalars(select(ReviewQueue).where(ReviewQueue.field == "cluster")).all()
    assert len(review) == 1 and review[0].payload["event_id"] == late.id


@pytest.mark.parametrize(
    "overrides",
    [
        # Near-identical text but no shared resolved entity: never a candidate.
        {"headline": "CPI twin", "url": "https://ex.com/3",
         "entities": [(SULLIVAN, "subject", "Sullivan")]},
        # Same entity and text, but outside the ±48h window (e.g. next month's release).
        {"headline": "CPI twin", "url": "https://ex.com/4",
         "event_time": T0 + timedelta(hours=72)},
    ],
)
def test_similar_text_without_overlap_or_outside_window_is_new(
    seeded_db: Session, cpi_corpus: dict[str, Event], fake_embed: FakeEmbedder,
    fake_llm: Any, overrides: dict[str, Any],
) -> None:
    embed_pending(seeded_db)
    cluster_pending(seeded_db)
    fake_embed.set("CPI twin", unit_vec(0.99, 8))
    twin = add_member(seeded_db, CPI_NEWS, **overrides)
    embed_pending(seeded_db)

    stats = cluster_pending(seeded_db)

    assert stats.new == 1 and twin.cluster_id not in (None, cpi_corpus["bls"].cluster_id)
    assert fake_llm.calls == []


def test_real_bge_on_fixture_corpus(seeded_db: Session, fake_llm: Any) -> None:
    """Sanity check of the default thresholds against the real dev model (skips if not cached).

    Measured cosines vs the BLS release: news 0.86 (attach), senator's reaction 0.75 (tiebreak),
    nomination 0.45 (new).
    """
    try:
        from brokeberg.embed import _local_model

        _local_model()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"bge model not available offline: {e}")
    fake_llm.set(SameEvent, SameEvent(same=True, reason="same release", confidence=0.9))
    events = [add_member(seeded_db, i) for i in (CPI_BLS, CPI_NEWS, CPI_REACTION, NOMINATION)]

    embed_pending(seeded_db)
    stats = cluster_pending(seeded_db)

    bls, news, reaction, nom = events
    assert bls.cluster_id == news.cluster_id == reaction.cluster_id != nom.cluster_id
    assert stats.tiebreaks == 1  # the reaction, and only the reaction
