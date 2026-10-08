"""Pass 7: verify one event object and write the verdict back onto the head.

`verification_status` reflects only the event's factual checks:
fact_checked > corroborated > single_source (> unverified). A numeric claim that disagrees with
FRED/BLS is an event-level flag (`verification.numeric_mismatch`) and, if nothing matches, a
confidence penalty. A stance flip is not a fact about the event: it is marked on the stance row
(`contradict.mark_flips`) and never changes the status.

Confidence is recomputed from the members every time, then penalized, so re-running never
compounds a penalty. Stance flips, numeric mismatches and low confidence go to review.
"""

from typing import Any

from sqlalchemy.orm import Session

from brokeberg.cluster.cluster import members, review_raw_item
from brokeberg.cluster.event_object import member_tiers, rolled_confidence
from brokeberg.config import Settings
from brokeberg.db.models import Event, ReviewKind
from brokeberg.extract.doc import ReviewItem
from brokeberg.extract.run import write_review
from brokeberg.taxonomy import VerificationStatus
from brokeberg.verify import contradict, corroborate, numeric


def _reviews(
    head: Event, verification: dict[str, Any], flips: list[dict[str, Any]], penalized: bool,
    settings: Settings,
) -> list[ReviewItem]:
    items = []
    if flips:
        items.append(ReviewItem(
            kind=ReviewKind.VERIFICATION, mention=head.headline, field="verify:stance_flip",
            payload={"head_id": head.id, "flips": flips},
        ))
    mismatches = [c for c in verification["numeric"] if c["result"] == "mismatch"]
    if mismatches or verification["reference_disagreements"]:
        items.append(ReviewItem(
            kind=ReviewKind.VERIFICATION, mention=head.headline, field="verify:numeric",
            payload={
                "head_id": head.id, "mismatches": mismatches, "penalized": penalized,
                "reference_disagreements": verification["reference_disagreements"],
            },
        ))
    if head.confidence < settings.verify_review_confidence:
        items.append(ReviewItem(
            kind=ReviewKind.LOW_CONFIDENCE, mention=head.headline, field="verify:confidence",
            payload={"head_id": head.id}, confidence=head.confidence,
        ))
    return items


def verify_head(session: Session, head: Event, settings: Settings) -> VerificationStatus:
    assert head.cluster_id == head.id, f"event {head.id} is not a cluster head"
    corr = corroborate.corroborate(session, head)
    num = numeric.check(session, head, settings)
    flips = contradict.mark_flips(session, head, settings)

    status = VerificationStatus.FACT_CHECKED if num.fact_checked else corr.status

    ms = members(session, head.id)
    tiers = member_tiers(session, [m.id for m in ms])
    base = rolled_confidence(tiers, ms) if ms else head.confidence
    confidence = base * settings.verify_numeric_penalty if num.penalize else base

    verification: dict[str, Any] = {
        "independent_sources": corr.independent_sources,
        "corroboration_score": corr.score,
        "source_keys": corr.keys,
        "numeric": num.checks,
        "numeric_mismatch": num.mismatched,
        "reference_disagreements": num.disagreements,
        "base_confidence": round(base, 6),
    }
    if head.verification_status != status:
        head.verification_status = status
    if head.verification != verification:
        head.verification = verification
    if abs(head.confidence - confidence) > 1e-9:
        head.confidence = confidence
    session.flush()

    items = _reviews(head, verification, flips, num.penalize, settings)
    if items and ms and (raw_item_id := review_raw_item(session, ms[0])) is not None:
        write_review(session, raw_item_id, items)
    return status
