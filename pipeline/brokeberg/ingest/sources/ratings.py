"""Topline Senate race ratings -> `race_ratings_history`, then `races.rating` from the newest row.

Weekly cadence. Every page is gated by `robots_ok()`, rate limited, and cached on disk for
`CACHE_TTL`, so running more often than weekly does not re-hit the raters.

Raters:
- Cook Political Report: the public ratings page (cards per rating column). It has no per-race
  date, so `asof` is the date we observed the page (the response `Date` header).
- Inside Elections: the JSON feed behind their ratings page, which carries a date per race.
- Sabato's Crystal Ball: centerforpolitics.org serves a bot challenge (robots.txt included), so
  `robots_ok()` refuses it and it is skipped with a log line. No parser until it is reachable.

Rating labels map through explicit tables; an unknown label is logged and skipped, never guessed.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
from selectolax.lexbor import LexborHTMLParser
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from brokeberg.db.models import Race, RaceRatingHistory
from brokeberg.db.seed import race_id as senate_race_id
from brokeberg.ids import fips
from brokeberg.ingest import http
from brokeberg.ingest.base import Stats
from brokeberg.taxonomy import RaceRating as R

log = logging.getLogger(__name__)

DEFAULT_CACHE = Path(__file__).resolve().parents[3] / ".cache" / "ratings"
CACHE_TTL = timedelta(days=7)

COOK_URL = "https://www.cookpolitical.com/ratings/senate-race-ratings"
IE_URL = (
    "https://insideelections.com/wp-content/themes/inside-elections/cache/"
    "ratings_latest_senate_year={year}_district=all_clean.json"
)
IE_PAGE = "https://insideelections.com/ratings/senate"
SABATO_URL = "https://centerforpolitics.org/crystalball/{year}-senate/"

COOK_LABELS: dict[str, R] = {
    "solid democrat": R.SAFE_D, "likely democrat": R.LIKELY_D, "lean democrat": R.LEAN_D,
    "toss up": R.TOSSUP,
    "lean republican": R.LEAN_R, "likely republican": R.LIKELY_R, "solid republican": R.SAFE_R,
}
IE_LABELS: dict[str, R] = {
    "solid democrat": R.SAFE_D, "safe democrat": R.SAFE_D, "likely democrat": R.LIKELY_D,
    "lean democrat": R.LEAN_D, "tilt democrat": R.TOSSUP_D, "toss-up": R.TOSSUP,
    "tilt republican": R.TOSSUP_R, "lean republican": R.LEAN_R,
    "likely republican": R.LIKELY_R, "solid republican": R.SAFE_R, "safe republican": R.SAFE_R,
}
# Tie-break when raters publish on the same day (for `races.rating` only); code, not judgment.
RATER_PRIORITY = ("cook", "inside_elections", "sabato")


@dataclass(frozen=True)
class Rating:
    state: str  # USPS abbreviation
    rating: R
    asof: date


@dataclass(frozen=True)
class Page:
    body: str
    fetched: datetime


@dataclass(frozen=True)
class Rater:
    name: str
    url: str  # the URL we fetch
    source_url: str  # the human-facing page cited as provenance
    parse: Callable[[Page], list[Rating]] | None


def parse_cook(page: Page) -> list[Rating]:
    tree = LexborHTMLParser(page.body)
    out = []
    for card in tree.css("div.race-card"):
        header = card.css_first(".race-card-header")
        if header is None:
            continue
        label = next((k for k in COOK_LABELS if k in header.text().lower()), None)
        if label is None:
            log.warning("cook: unknown rating header %r", header.text().strip())
            continue
        for item in card.css("span.race-district"):
            out.append(Rating(item.text().strip(), COOK_LABELS[label], page.fetched.date()))
    return out


def parse_inside_elections(page: Page) -> list[Rating]:
    out = []
    for row in json.loads(page.body).get("ratings", []):
        rating = IE_LABELS.get(str(row.get("rating", "")).strip().lower())
        if rating is None:
            log.warning("inside_elections: unknown rating %r", row.get("rating"))
            continue
        asof = datetime.fromisoformat(row["date"]).date()
        out.append(Rating(str(row["district"]).upper(), rating, asof))
    return out


def raters(year: int) -> tuple[Rater, ...]:
    return (
        Rater("cook", COOK_URL, COOK_URL, parse_cook),
        Rater("inside_elections", IE_URL.format(year=year), IE_PAGE, parse_inside_elections),
        Rater("sabato", SABATO_URL.format(year=year), SABATO_URL.format(year=year), None),
    )


class RatingsLoader:
    source = "ratings"

    def __init__(
        self, client: httpx.Client | None = None, cache_dir: Path | None = DEFAULT_CACHE
    ) -> None:
        self.client = client or http.make_client()
        self.cache_dir = cache_dir

    def _fetch(self, rater: Rater) -> Page:
        cache = self.cache_dir / f"{rater.name}.json" if self.cache_dir else None
        fresh = cache is not None and cache.exists() and (
            time.time() - cache.stat().st_mtime < CACHE_TTL.total_seconds()
        )
        if cache is not None and fresh:
            data = json.loads(cache.read_text(encoding="utf-8"))
            return Page(data["body"], datetime.fromisoformat(data["fetched"]))
        resp = http.get(self.client, rater.url)
        header = resp.headers.get("date")
        fetched = parsedate_to_datetime(header) if header else datetime.now(UTC)
        page = Page(resp.text, fetched)
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            payload = {"fetched": fetched.isoformat(), "body": page.body}
            cache.write_text(json.dumps(payload), encoding="utf-8")
        return page

    def load(self, session: Session, since: datetime) -> Stats:
        stats = Stats(source=self.source)
        races = {r.id for r in session.scalars(select(Race).where(Race.cycle == since.year))}
        skipped_raters = []
        for rater in raters(since.year):
            reason = None
            if not http.robots_ok(self.client, rater.url):
                reason = "robots.txt"
            elif rater.parse is None:
                reason = "no parser"
            if reason or rater.parse is None:
                log.info("ratings: skipping %s (%s)", rater.name, reason)
                skipped_raters.append(rater.name)
                continue
            try:
                ratings = rater.parse(self._fetch(rater))
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                log.warning("ratings: %s failed (%s); skipping", rater.name, exc)
                skipped_raters.append(rater.name)
                continue
            for rating in ratings:
                state = fips.lookup(rating.state)
                rid = senate_race_id(state.abbrev) if state else None
                if rid not in races:
                    continue  # outside the MVP race set
                stats.fetched += 1
                if self._upsert(session, rid, rater, rating):
                    stats.inserted += 1
                else:
                    stats.skipped += 1
        session.flush()
        self._refresh_current(session, races)
        if skipped_raters:
            stats.note = f"skipped raters: {', '.join(skipped_raters)}"
        return stats

    @staticmethod
    def _upsert(session: Session, race_id: str, rater: Rater, rating: Rating) -> bool:
        base = insert(RaceRatingHistory).values(
            race_id=race_id, rater=rater.name, rating=rating.rating, asof=rating.asof,
            source_url=rater.source_url,
        )
        stmt = base.on_conflict_do_update(
            constraint="uq_race_ratings_history_race_rater_asof",
            set_={"rating": base.excluded.rating, "source_url": base.excluded.source_url},
            where=RaceRatingHistory.rating.is_distinct_from(base.excluded.rating),
        ).returning(RaceRatingHistory.id)
        return session.execute(stmt).first() is not None

    @staticmethod
    def _refresh_current(session: Session, race_ids: set[str]) -> None:
        """`races.rating` = newest sourced history row; same-day ties go by RATER_PRIORITY."""
        for rid in race_ids:
            rows = session.scalars(
                select(RaceRatingHistory).where(RaceRatingHistory.race_id == rid)
            ).all()
            if not rows:
                continue

            def key(row: RaceRatingHistory) -> tuple[date, int]:
                prio = RATER_PRIORITY.index(row.rater) if row.rater in RATER_PRIORITY else 99
                return (row.asof, -prio)

            newest = max(rows, key=key)
            race = session.get(Race, rid)
            if race is not None and race.rating != newest.rating:
                race.rating = newest.rating
