"""Independent-source count for one event object (a cluster head).

Counts the head's own `event_sources`, which `rollup` copied from every member: a cluster of
three reports is one event with three sources, never three events. Two sources are independent
when their (source_type, origin) keys differ; the origin is the domain, plus the account for social
posts (two X accounts are two voices, two pages on one site are one).
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.cluster.event_object import TRUST_WEIGHT
from brokeberg.db.models import Event, EventSource, RawItem
from brokeberg.taxonomy import SourceType, TrustTier, VerificationStatus


def _rank(tier: TrustTier) -> int:
    return int(tier.value[1:])


def independence_key(source_type: SourceType | None, url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").removeprefix("www.")
    origin = host
    if source_type == SourceType.SOCIAL_POST:
        account = parts.path.strip("/").split("/", 1)[0].lower()
        origin = f"{host}/{account}" if account else host
    return f"{source_type.value if source_type else 'unknown'}|{origin}"


@dataclass(frozen=True)
class Corroboration:
    status: VerificationStatus
    independent_sources: int
    # Sum of trust weights over independent sources (best tier per source).
    score: float
    keys: list[str]


def corroborate(session: Session, head: Event) -> Corroboration:
    best: dict[str, TrustTier] = {}
    for url, tier, source_type in session.execute(
        select(EventSource.url, EventSource.trust_tier, RawItem.source_type)
        .outerjoin(RawItem, RawItem.id == EventSource.raw_item_id)
        .where(EventSource.event_id == head.id)
    ):
        key = independence_key(source_type, url)
        if key not in best or _rank(tier) < _rank(best[key]):
            best[key] = tier
    n = len(best)
    status = (
        VerificationStatus.CORROBORATED if n >= 2
        else VerificationStatus.SINGLE_SOURCE if n == 1
        else VerificationStatus.UNVERIFIED
    )
    return Corroboration(
        status=status,
        independent_sources=n,
        score=round(sum(TRUST_WEIGHT[t] for t in best.values()), 4),
        keys=sorted(best),
    )
