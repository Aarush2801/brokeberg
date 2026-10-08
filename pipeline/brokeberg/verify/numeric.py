"""Check numeric economic claims in an event's source spans against `indicators`.

Deterministic: a span is checked only for an `EconomicIndicator` the event already links to (via
the FRED common-usage aliases), and only when the span names that series. The claim is parsed
by regex, the reference is computed from stored observations, separately per source: BLS values
sit under the same FRED series ID, so FRED and BLS each check the claim and each other.

Period: the month the span names; otherwise the month before the event (monthly releases report
the prior month).
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.config import Settings
from brokeberg.db.models import Entity, Event, EventEntity, EventSource, Indicator
from brokeberg.ids.canonical import Namespace, split
from brokeberg.taxonomy import EntityType, TrustTier


class Kind(StrEnum):
    PCT_CHANGE = "pct_change"  # % change of an index level, m/m (or y/y)
    RATE = "rate"  # the level is itself a percentage
    CHANGE_THOUSANDS = "change_thousands"  # m/m change of a level kept in thousands


SERIES_KIND: dict[str, Kind] = {
    "CPIAUCSL": Kind.PCT_CHANGE,
    "CPILFESL": Kind.PCT_CHANGE,
    "PCEPI": Kind.PCT_CHANGE,
    "PCEPILFE": Kind.PCT_CHANGE,
    "UNRATE": Kind.RATE,
    "CIVPART": Kind.RATE,
    "PAYEMS": Kind.CHANGE_THOUSANDS,
}
# The jobs regex names its own series, so payroll spans need no alias match.
SELF_NAMED: frozenset[str] = frozenset({"PAYEMS"})

_DOWN = frozenset({"fell", "declined", "dropped", "decreased", "slipped", "down", "lost", "shed",
                   "cut"})
_PCT = re.compile(
    r"\b(?P<verb>rose|increased|climbed|jumped|surged|gained|advanced|accelerated|up|fell|"
    r"declined|dropped|decreased|slipped|down|hit|was|is|at|of|to)\s+(?:by\s+|to\s+|a\s+)?"
    r"(?P<num>\d+(?:\.\d+)?)\s*(?:%|percent\b|per\s+cent\b)",
    re.I,
)
_JOBS = re.compile(
    r"\b(?P<verb>added|gained|created|lost|shed|cut)\s+"
    r"(?:a\s+net\s+|about\s+|roughly\s+|nearly\s+|just\s+)?(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>thousand|million|k\b)?\s+(?:\w+\s+)?jobs\b",
    re.I,
)
_YOY = re.compile(
    r"from a year (?:ago|earlier)|over the (?:past|last|prior) (?:12|twelve) months|"
    r"year[- ]over[- ]year|\byoy\b|\bannual(?:ly)?\b|12-month",
    re.I,
)
_MONTH = re.compile(
    r"\b(?P<month>" + "|".join(calendar.month_name[1:]) + r")\b(?:,?\s+(?P<year>\d{4}))?", re.I
)
_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}


def _shift(d: date, months: int) -> date:
    n = d.year * 12 + d.month - 1 + months
    return date(n // 12, n % 12 + 1, 1)


def _period(span: str, event_time: datetime) -> date:
    m = _MONTH.search(span)
    if m is None:
        return _shift(date(event_time.year, event_time.month, 1), -1)
    month = _MONTHS[m.group("month").lower()]
    if m.group("year"):
        return date(int(m.group("year")), month, 1)
    year = event_time.year if month <= event_time.month else event_time.year - 1
    return date(year, month, 1)


@dataclass(frozen=True)
class Claim:
    series_id: str
    kind: Kind
    value: float
    yoy: bool
    period: date
    text: str


def _alias_match(span: str, aliases: list[str]) -> int:
    """Length of the longest alias the span names (0 if none)."""
    best = 0
    for a in aliases:
        if len(a) > best and re.search(rf"(?<!\w){re.escape(a)}(?!\w)", span, re.I):
            best = len(a)
    return best


def _parse(span: str, series_id: str, kind: Kind, event_time: datetime) -> Claim | None:
    if kind == Kind.CHANGE_THOUSANDS:
        m = _JOBS.search(span)
        if m is None:
            return None
        num = float(m.group("num").replace(",", ""))
        unit = (m.group("unit") or "").lower()
        scale = {"thousand": 1.0, "k": 1.0, "million": 1000.0}.get(unit, 0.001)
        value = num * scale
    else:
        m = _PCT.search(span)
        if m is None:
            return None
        value = float(m.group("num"))
    if m.group("verb").lower() in _DOWN:
        value = -value
    return Claim(
        series_id=series_id,
        kind=kind,
        value=value,
        yoy=kind == Kind.PCT_CHANGE and _YOY.search(span) is not None,
        period=_period(span, event_time),
        text=m.group(0),
    )


def parse_claim(
    span: str, series: dict[str, list[str]], event_time: datetime
) -> Claim | None:
    """The claim in `span` about one of `series` (series_id -> aliases); the series the span names
    most specifically ("core CPI" beats "CPI") wins. None if the span makes no checkable claim."""
    ranked = []
    for sid, aliases in series.items():
        kind = SERIES_KIND.get(sid)
        if kind is None:
            continue
        score = _alias_match(span, aliases)
        if score == 0 and sid not in SELF_NAMED:
            continue
        ranked.append((score, sid, kind))
    for _, sid, kind in sorted(ranked, key=lambda r: (-r[0], r[1])):
        claim = _parse(span, sid, kind, event_time)
        if claim is not None:
            return claim
    return None


def reference_values(session: Session, claim: Claim) -> dict[str, float]:
    """The claimed quantity computed from stored observations, per source ('fred', 'bls')."""
    prior = _shift(claim.period, -12 if claim.yoy else -1)
    obs: dict[tuple[str, date], float] = {
        (source, asof): float(value)
        for source, asof, value in session.execute(
            select(Indicator.source, Indicator.asof, Indicator.value).where(
                Indicator.series_id == claim.series_id,
                Indicator.asof.in_([claim.period, prior]),
            )
        )
    }
    out: dict[str, float] = {}
    for source in sorted({s for s, _ in obs}):
        cur, prev = obs.get((source, claim.period)), obs.get((source, prior))
        if cur is None:
            continue
        if claim.kind == Kind.RATE:
            out[source] = cur
        elif prev is None:
            continue
        elif claim.kind == Kind.PCT_CHANGE:
            out[source] = (cur / prev - 1) * 100
        else:
            out[source] = cur - prev
    return out


def _tolerance(kind: Kind, settings: Settings) -> float:
    if kind == Kind.CHANGE_THOUSANDS:
        return settings.verify_numeric_tol_thousands
    return settings.verify_numeric_tol_pct


@dataclass
class NumericResult:
    checks: list[dict[str, Any]] = field(default_factory=list)
    # FRED and BLS disagreeing with each other on the same quantity.
    disagreements: list[dict[str, Any]] = field(default_factory=list)

    def _results(self) -> list[str]:
        return [c["result"] for c in self.checks]

    @property
    def mismatched(self) -> bool:
        return "mismatch" in self._results()

    @property
    def matched(self) -> bool:
        return "match" in self._results()

    @property
    def fact_checked(self) -> bool:
        """A primary-ish (T1/T2) source's number matches the data, and nothing contradicts it."""
        return not self.mismatched and any(
            c["result"] == "match" and c["trust_tier"] in (TrustTier.T1, TrustTier.T2)
            for c in self.checks
        )

    @property
    def penalize(self) -> bool:
        return self.mismatched and not self.matched


def linked_series(session: Session, head: Event) -> dict[str, list[str]]:
    """FRED series the head links to -> the surfaces that name them (name + aliases)."""
    out: dict[str, list[str]] = {}
    for canonical_id, name, aliases in session.execute(
        select(Entity.canonical_id, Entity.name, Entity.aliases)
        .join(EventEntity, EventEntity.entity_id == Entity.id)
        .where(
            EventEntity.event_id == head.id,
            Entity.entity_type == EntityType.ECONOMIC_INDICATOR,
        )
        .distinct()
    ):
        ns, sid = split(canonical_id)
        if ns == Namespace.FRED:
            out[sid] = list(dict.fromkeys([name, *aliases]))
    return out


def check(session: Session, head: Event, settings: Settings) -> NumericResult:
    result = NumericResult()
    series = linked_series(session, head)
    if not series:
        return result
    seen_disagreement: set[tuple[str, date, bool]] = set()
    for src in session.scalars(
        select(EventSource)
        .where(EventSource.event_id == head.id)
        .order_by(EventSource.trust_tier, EventSource.id)
    ):
        claim = parse_claim(src.span, series, head.event_time)
        if claim is None:
            continue
        refs = reference_values(session, claim)
        tol = _tolerance(claim.kind, settings)
        if not refs:
            outcome = "no_reference"
        elif any(abs(claim.value - v) <= tol + 1e-9 for v in refs.values()):
            outcome = "match"
        else:
            outcome = "mismatch"
        result.checks.append({
            "url": src.url, "span": src.span, "trust_tier": src.trust_tier,
            "series_id": claim.series_id, "kind": claim.kind, "yoy": claim.yoy,
            "period": claim.period.isoformat(), "claimed": claim.value, "claim_text": claim.text,
            "references": {k: round(v, 4) for k, v in refs.items()}, "result": outcome,
        })
        key = (claim.series_id, claim.period, claim.yoy)
        if {"fred", "bls"} <= refs.keys() and key not in seen_disagreement:
            seen_disagreement.add(key)
            if abs(refs["fred"] - refs["bls"]) > tol + 1e-9:
                result.disagreements.append({
                    "series_id": claim.series_id, "period": claim.period.isoformat(),
                    "yoy": claim.yoy, "fred": round(refs["fred"], 4), "bls": round(refs["bls"], 4),
                })
    return result
