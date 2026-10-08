from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from cluster_corpus import CPI_BLS, CPI_NEWS, CPI_REACTION, MURKOWSKI, NOMINATION, T0, entity_id
from graph_corpus import MURKOWSKI_EARLIER, WRONG_CPI_POST, cluster_of, seed_cpi
from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.config import get_settings
from brokeberg.db.models import Event, EventEntity, ReviewKind, ReviewQueue
from brokeberg.taxonomy import SourceType, Stance, Topic, VerificationStatus
from brokeberg.verify import contradict
from brokeberg.verify.corroborate import corroborate, independence_key
from brokeberg.verify.numeric import Kind, parse_claim
from brokeberg.verify.run import verify_head

CPI_SERIES = {
    "CPIAUCSL": ["Consumer Price Index for All Urban Consumers: All Items", "CPI", "inflation",
                 "consumer prices", "consumer price index"],
    "CPILFESL": ["core CPI", "core inflation"],
    "PAYEMS": ["payrolls", "jobs report"],
}
SEP = datetime(2026, 9, 10, tzinfo=UTC)


def _verify(db: Session, head: Event) -> VerificationStatus:
    return verify_head(db, head, get_settings())


def _reviews(db: Session, field: str) -> list[ReviewQueue]:
    return list(db.scalars(select(ReviewQueue).where(ReviewQueue.field == field)))


# --- corroboration -----------------------------------------------------------------------------


def test_independence_key() -> None:
    news = SourceType.NEWS
    assert independence_key(news, "https://www.nytimes.com/a") == independence_key(
        news, "https://nytimes.com/b"
    )
    post = SourceType.SOCIAL_POST
    assert independence_key(post, "https://x.com/alice/status/1") != independence_key(
        post, "https://x.com/bob/status/2"
    )
    assert independence_key(post, "https://x.com/Alice/status/1") == independence_key(
        post, "https://x.com/alice/status/3"
    )


def test_single_source_event(seeded_db: Session) -> None:
    head = cluster_of(seeded_db, NOMINATION)
    assert _verify(seeded_db, head) == VerificationStatus.SINGLE_SOURCE
    assert head.verification_status == VerificationStatus.SINGLE_SOURCE
    assert head.verification["independent_sources"] == 1


def test_cluster_sources_corroborate_as_one_event(seeded_db: Session) -> None:
    """Three members, one event: corroboration counts the head's sources, not three events."""
    head = cluster_of(seeded_db, CPI_BLS, CPI_NEWS, CPI_REACTION)
    c = corroborate(seeded_db, head)
    assert c.status == VerificationStatus.CORROBORATED
    assert c.independent_sources == 3
    assert c.score == pytest.approx(1.0 + 0.6 + 0.4)
    # No indicator data: nothing to fact-check against, so corroboration decides.
    assert _verify(seeded_db, head) == VerificationStatus.CORROBORATED


def test_same_outlet_twice_is_single_source(seeded_db: Session) -> None:
    second = CPI_NEWS.__class__(**{
        **CPI_NEWS.__dict__, "headline": "Inflation picks up in August",
        "url": "https://www.nytimes.com/live/2026/09/10/cpi-updates",
        "span": "Prices picked up in August, the Labor Department said",
    })
    head = cluster_of(seeded_db, CPI_NEWS, second)
    assert _verify(seeded_db, head) == VerificationStatus.SINGLE_SOURCE


# --- numeric -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("span", "series_id", "kind", "value", "yoy", "month"),
    [
        ("The Consumer Price Index increased 0.4 percent in August", "CPIAUCSL",
         Kind.PCT_CHANGE, 0.4, False, 8),
        ("Core CPI rose 0.3% in August", "CPILFESL", Kind.PCT_CHANGE, 0.3, False, 8),
        ("Inflation hit 2.9% over the past 12 months", "CPIAUCSL", Kind.PCT_CHANGE, 2.9, True, 8),
        ("Consumer prices fell 0.1% in July", "CPIAUCSL", Kind.PCT_CHANGE, -0.1, False, 7),
        ("The economy added 142,000 jobs in August", "PAYEMS", Kind.CHANGE_THOUSANDS, 142.0,
         False, 8),
        ("Employers shed 1.2 million jobs", "PAYEMS", Kind.CHANGE_THOUSANDS, -1200.0, False, 8),
        ("CPI rose 0.4% in December", "CPIAUCSL", Kind.PCT_CHANGE, 0.4, False, 12),
    ],
)
def test_parse_claim(
    span: str, series_id: str, kind: Kind, value: float, yoy: bool, month: int
) -> None:
    claim = parse_claim(span, CPI_SERIES, SEP)
    assert claim is not None
    assert (claim.series_id, claim.kind, claim.value, claim.yoy) == (series_id, kind, value, yoy)
    assert claim.period.month == month
    # A named month later in the year than the event is last year's.
    assert claim.period.year == (2025 if month > 9 else 2026)


@pytest.mark.parametrize(
    "span",
    [
        "CPI came in above the 0.3% economists expected",  # an expectation, not a reading
        "Shares rose 2% on the news",  # names no linked series
        "CPI report due Wednesday",  # no number
    ],
)
def test_parse_claim_ignores(span: str) -> None:
    assert parse_claim(span, CPI_SERIES, SEP) is None


def test_matching_cpi_number_is_fact_checked(seeded_db: Session) -> None:
    seed_cpi(seeded_db)
    head = cluster_of(seeded_db, CPI_BLS, CPI_NEWS, CPI_REACTION)
    assert _verify(seeded_db, head) == VerificationStatus.FACT_CHECKED
    checks = head.verification["numeric"]
    assert {c["result"] for c in checks} == {"match"}
    assert len(checks) == 3
    bls = next(c for c in checks if "bls.gov" in c["url"])
    assert bls["period"] == "2026-08-01"
    assert bls["references"] == {"bls": pytest.approx(0.4), "fred": pytest.approx(0.4)}
    assert head.verification["reference_disagreements"] == []


def test_wrong_cpi_post_is_flagged_and_penalized(seeded_db: Session) -> None:
    seed_cpi(seeded_db)
    head = cluster_of(seeded_db, WRONG_CPI_POST)
    base = head.confidence
    status = _verify(seeded_db, head)

    assert status == VerificationStatus.SINGLE_SOURCE  # a flag, not a status
    [check] = head.verification["numeric"]
    assert check["result"] == "mismatch"
    assert check["claimed"] == 0.9
    assert check["span"] == WRONG_CPI_POST.span
    assert head.confidence == pytest.approx(base * get_settings().verify_numeric_penalty)
    [review] = _reviews(seeded_db, "verify:numeric")
    assert review.kind == ReviewKind.VERIFICATION
    assert review.payload["penalized"] is True


def test_wrong_post_in_a_good_cluster_is_surfaced_not_penalized(seeded_db: Session) -> None:
    seed_cpi(seeded_db)
    head = cluster_of(seeded_db, CPI_BLS, WRONG_CPI_POST)
    base = head.confidence
    assert _verify(seeded_db, head) == VerificationStatus.CORROBORATED  # not fact_checked
    assert sorted(c["result"] for c in head.verification["numeric"]) == ["match", "mismatch"]
    assert head.confidence == pytest.approx(base)
    assert _reviews(seeded_db, "verify:numeric")


def test_bls_cross_checks_fred(seeded_db: Session) -> None:
    seed_cpi(seeded_db, bls_aug=Decimal("321.920"))  # BLS says +0.6%, FRED +0.4%
    head = cluster_of(seeded_db, CPI_BLS)
    _verify(seeded_db, head)
    [d] = head.verification["reference_disagreements"]
    assert (d["series_id"], d["fred"], d["bls"]) == (
        "CPIAUCSL", pytest.approx(0.4), pytest.approx(0.6)
    )
    assert head.verification["numeric"][0]["result"] == "match"  # FRED still agrees
    assert _reviews(seeded_db, "verify:numeric")


def test_no_indicator_data_is_no_reference(seeded_db: Session) -> None:
    head = cluster_of(seeded_db, CPI_BLS)
    _verify(seeded_db, head)
    assert [c["result"] for c in head.verification["numeric"]] == ["no_reference"]


# --- stance flips (on the stance row, never the event status) ----------------------------------


def _stance_row(db: Session, head: Event) -> EventEntity:
    [row] = db.scalars(
        select(EventEntity).where(
            EventEntity.event_id == head.id,
            EventEntity.entity_id == entity_id(db, MURKOWSKI),
            EventEntity.topic == Topic.INFLATION_COST_OF_LIVING,
        )
    ).all()
    return row


def test_stance_flip_is_marked_on_the_stance_not_the_event(seeded_db: Session) -> None:
    earlier = cluster_of(seeded_db, MURKOWSKI_EARLIER)
    later = cluster_of(seeded_db, CPI_REACTION)
    assert _verify(seeded_db, earlier) == VerificationStatus.SINGLE_SOURCE
    assert _verify(seeded_db, later) == VerificationStatus.SINGLE_SOURCE  # facts only

    flip = _stance_row(seeded_db, later).stance_flip
    assert flip is not None
    assert (flip["prior_event_id"], flip["prior_stance"]) == (earlier.id, Stance.SUPPORT)
    assert flip["prior_span"] == MURKOWSKI_EARLIER.stances[0][3]
    assert flip["prior_source_url"] == MURKOWSKI_EARLIER.url
    assert _stance_row(seeded_db, later).stance == Stance.OPPOSE  # both stances kept
    assert _stance_row(seeded_db, earlier).stance_flip is None
    assert "contradictions" not in later.verification
    [review] = _reviews(seeded_db, "verify:stance_flip")
    assert review.kind == ReviewKind.VERIFICATION
    assert review.payload["flips"][0]["prior_event_id"] == earlier.id


def test_fact_checked_event_with_a_flipped_stance_stays_fact_checked(seeded_db: Session) -> None:
    seed_cpi(seeded_db)
    cluster_of(seeded_db, MURKOWSKI_EARLIER)
    head = cluster_of(seeded_db, CPI_BLS, CPI_NEWS, CPI_REACTION)
    assert _verify(seeded_db, head) == VerificationStatus.FACT_CHECKED
    assert head.verification["numeric_mismatch"] is False
    assert _stance_row(seeded_db, head).stance_flip is not None


def test_drift_to_neutral_is_not_a_flip(seeded_db: Session) -> None:
    cluster_of(seeded_db, MURKOWSKI_EARLIER, stances=[(
        MURKOWSKI, Topic.INFLATION_COST_OF_LIVING, Stance.LEAN_SUPPORT,
        MURKOWSKI_EARLIER.span,
    )])
    later = cluster_of(seeded_db, CPI_REACTION, stances=[(
        MURKOWSKI, Topic.INFLATION_COST_OF_LIVING, Stance.NEUTRAL_UNCLEAR,
        "Alaska families are still squeezed.",
    )])
    _verify(seeded_db, later)
    assert _stance_row(seeded_db, later).stance_flip is None
    assert _reviews(seeded_db, "verify:stance_flip") == []


def test_flip_sides() -> None:
    assert contradict.is_flip(Stance.SUPPORT, Stance.LEAN_OPPOSE)
    assert contradict.is_flip(Stance.STRONGLY_OPPOSE, Stance.LEAN_SUPPORT)
    assert not contradict.is_flip(Stance.SUPPORT, Stance.STRONGLY_SUPPORT)
    assert not contradict.is_flip(Stance.NEUTRAL_UNCLEAR, Stance.OPPOSE)


def test_flip_is_judged_by_event_time_not_insert_order(seeded_db: Session) -> None:
    later = cluster_of(seeded_db, CPI_REACTION)
    earlier = cluster_of(seeded_db, MURKOWSKI_EARLIER, event_time=T0 - timedelta(days=5))
    _verify(seeded_db, earlier)
    _verify(seeded_db, later)
    assert _stance_row(seeded_db, earlier).stance_flip is None
    assert _stance_row(seeded_db, later).stance_flip is not None


def test_flip_marker_clears_when_the_prior_stance_goes_away(seeded_db: Session) -> None:
    earlier = cluster_of(seeded_db, MURKOWSKI_EARLIER)
    later = cluster_of(seeded_db, CPI_REACTION)
    _verify(seeded_db, later)
    assert _stance_row(seeded_db, later).stance_flip is not None
    _stance_row(seeded_db, earlier).stance = Stance.OPPOSE  # e.g. corrected in review
    seeded_db.flush()
    _verify(seeded_db, later)
    assert _stance_row(seeded_db, later).stance_flip is None


# --- idempotency -------------------------------------------------------------------------------


def test_verify_is_idempotent(seeded_db: Session) -> None:
    seed_cpi(seeded_db)
    cluster_of(seeded_db, MURKOWSKI_EARLIER)
    head = cluster_of(seeded_db, WRONG_CPI_POST, CPI_REACTION)
    _verify(seeded_db, head)
    first = (head.verification_status, dict(head.verification), head.confidence)
    flip = _stance_row(seeded_db, head).stance_flip
    assert flip is not None
    reviews = seeded_db.scalars(select(ReviewQueue.id).order_by(ReviewQueue.id)).all()

    _verify(seeded_db, head)
    seeded_db.expire_all()
    head = seeded_db.get(Event, head.id)
    assert head is not None
    assert (head.verification_status, head.verification, head.confidence) == (
        first[0], first[1], pytest.approx(first[2])
    )
    assert _stance_row(seeded_db, head).stance_flip == flip
    assert seeded_db.scalars(select(ReviewQueue.id).order_by(ReviewQueue.id)).all() == reviews
