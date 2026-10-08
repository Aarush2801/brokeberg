"""Idempotent reference seeds: senators, state jurisdictions, target races, FRED series.

`python -m brokeberg.db.seed`. Every write is an upsert keyed on a canonical ID; rows whose
content is unchanged are not touched, so running it twice is a no-op. Senators come from the
committed `seed_data/senators.json` snapshot (refresh: `make fetch-senators`), never the network.
"""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from brokeberg.db.models import Entity, Race
from brokeberg.db.seed_data.fred_series import SERIES
from brokeberg.db.seed_data.races import CYCLE, RACES
from brokeberg.db.session import session_scope
from brokeberg.ids import fips
from brokeberg.ids.canonical import Namespace, make
from brokeberg.ids.resolve import clear_cache
from brokeberg.taxonomy import EntityType, JurisdictionLevel, RaceType

SENATORS_JSON = Path(__file__).parent / "seed_data" / "senators.json"
FRED_SERIES_URL = "https://fred.stlouisfed.org/series/{}"


def _dedupe(items: list[str | None]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        if item and item not in seen:
            seen[item] = None
    return list(seen)


def senator_aliases(s: dict[str, Any]) -> list[str]:
    # Honorific forms ("Sen. X") are not stored: `resolve.normalize` strips honorifics.
    tag = f"({s['party']}-{s['state']})"
    return _dedupe(
        [
            s["official_full"],
            f"{s['first']} {s['last']}",
            f"{s['nickname']} {s['last']}" if s["nickname"] else None,
            s["last"],
            f"{s['last']} {tag}",
            f"{s['first']} {s['last']} {tag}",
            f"@{s['twitter']}" if s["twitter"] else None,
            *s["fec"],
        ]
    )


def senator_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "entity_type": EntityType.POLITICIAN,
            "canonical_id": make(Namespace.BIOGUIDE, s["bioguide"]),
            "name": s["official_full"],
            "aliases": senator_aliases(s),
            "meta": {
                "chamber": "senate",
                "state": s["state"],
                "state_fips": fips.to_fips(s["state"]),
                "party": s["party"],
                "senate_class": s["senate_class"],
                "term_end": s["term_end"],
                "fec_ids": s["fec"],
                "lis": s.get("lis"),
                "twitter": s["twitter"],
                "ballotpedia": s["ballotpedia"],
                "source_urls": snapshot["source_urls"],
                "source_fetched_at": snapshot["fetched_at"],
            },
        }
        for s in snapshot["senators"]
    ]


def jurisdiction_rows() -> list[dict[str, Any]]:
    return [
        {
            "entity_type": EntityType.JURISDICTION,
            "canonical_id": make(Namespace.FIPS, st.fips),
            "name": st.name,
            "aliases": [st.abbrev, st.name],
            "meta": {"level": JurisdictionLevel.STATE, "fips": st.fips, "abbrev": st.abbrev},
        }
        for st in fips.STATES
    ]


def race_id(state: str) -> str:
    return f"{state}-SEN-{CYCLE}"


def race_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for r in RACES:
        state = fips.lookup(r.state)
        assert state is not None, r.state
        incumbent = next(
            (
                s["bioguide"]
                for s in snapshot["senators"]
                if s["state"] == r.state and s["senate_class"] == r.senate_class
            ),
            None,
        )
        kind = "special_election" if r.special else "election"
        rows.append(
            {
                "id": race_id(r.state),
                "state_fips": state.fips,
                "office": RaceType.SENATE,
                "cycle": CYCLE,
                "salient_topics": [t.value for t in r.salient_topics],
                "ballotpedia_slug": (
                    f"United_States_Senate_{kind}_in_{state.name.replace(' ', '_')},_{CYCLE}"
                ),
                "meta": {
                    "special": r.special,
                    "senate_class": r.senate_class,
                    "incumbent_bioguide": incumbent,
                },
            }
        )
    return rows


def race_entity_rows(races: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for race in races:
        state = fips.BY_FIPS[race["state_fips"]]
        special = " Special" if race["meta"]["special"] else ""
        name = f"{state.name} Senate{special} {race['cycle']}"
        rows.append(
            {
                "entity_type": EntityType.RACE,
                "canonical_id": make(Namespace.RACE, race["id"]),
                "name": name,
                "aliases": _dedupe([race["id"], name, f"{state.name} Senate race"]),
                "meta": {"race_id": race["id"], "state_fips": race["state_fips"]},
            }
        )
    return rows


def indicator_rows() -> list[dict[str, Any]]:
    return [
        {
            "entity_type": EntityType.ECONOMIC_INDICATOR,
            "canonical_id": make(Namespace.FRED, s.series_id),
            "name": s.title,
            "aliases": _dedupe([s.series_id, s.title, *s.aliases]),
            "meta": {
                "source": "FRED",
                "series_id": s.series_id,
                "frequency": s.frequency,
                "topic": s.topic.value,
                "url": FRED_SERIES_URL.format(s.series_id),
            },
        }
        for s in SERIES
    ]


def upsert_entities(session: Session, rows: list[dict[str, Any]]) -> None:
    stmt = insert(Entity).values(rows)
    ex = stmt.excluded
    changed = or_(
        Entity.entity_type.is_distinct_from(ex.entity_type),
        Entity.name.is_distinct_from(ex.name),
        Entity.aliases.is_distinct_from(ex.aliases),
        Entity.meta.is_distinct_from(ex.meta),
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Entity.canonical_id],
            set_={
                "entity_type": ex.entity_type,
                "name": ex.name,
                "aliases": ex.aliases,
                "meta": ex.meta,
                "updated_at": func.now(),
            },
            where=changed,
        )
    )


def upsert_races(session: Session, rows: list[dict[str, Any]]) -> None:
    # `rating` and `fec_candidate_ids` belong to ingestion (sourced); the seed never touches them.
    stmt = insert(Race).values(rows)
    ex = stmt.excluded
    cols = ("state_fips", "office", "cycle", "salient_topics", "ballotpedia_slug", "meta")
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Race.id],
            set_={c: getattr(ex, c) for c in cols},
            where=or_(*(getattr(Race, c).is_distinct_from(getattr(ex, c)) for c in cols)),
        )
    )


def seed(session: Session) -> dict[str, int]:
    snapshot = json.loads(SENATORS_JSON.read_text(encoding="utf-8"))
    races = race_rows(snapshot)
    upsert_entities(session, jurisdiction_rows())
    upsert_entities(session, senator_rows(snapshot))
    upsert_entities(session, indicator_rows())
    upsert_races(session, races)
    upsert_entities(session, race_entity_rows(races))
    session.flush()
    clear_cache()
    counts = session.execute(
        select(Entity.entity_type, func.count()).group_by(Entity.entity_type)
    ).all()
    result = {str(t): n for t, n in counts}
    result["races"] = session.scalar(select(func.count()).select_from(Race)) or 0
    return result


def main() -> None:
    with session_scope() as session:
        counts = seed(session)
    for name, n in sorted(counts.items()):
        print(f"{name:20} {n}")


if __name__ == "__main__":
    main()
