"""Terminal command arguments -> canonical references.

A name is a mention: it resolves to one entity ID through the alias index or the caller gets the
candidates back, never a guess. Every failure carries a direction the terminal can show as-is.
"""

import re

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brokeberg.db.models import Entity, HeadEvent, Race
from brokeberg.ids.resolve import resolve
from brokeberg.taxonomy import EntityType, Topic


class Option(BaseModel):
    """One way to narrow an ambiguous argument; `command` is runnable as typed."""

    label: str
    command: str


class Direction(Exception):
    """A reference that does not resolve: 404 (nothing matches) or 409 (several do)."""

    def __init__(self, status: int, message: str, options: list[Option] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.options = options or []


_EVENT_ID = re.compile(r"E?(\d+)", re.IGNORECASE)


def event_id(session: Session, ref: str) -> int:
    m = _EVENT_ID.fullmatch(ref.strip())
    if m is None:
        raise Direction(404, f"{ref} is not an event ID — use the number from FEED, e.g. EVT E42.")
    head_id = int(m.group(1))
    if session.scalar(select(HeadEvent.id).where(HeadEvent.id == head_id)) is None:
        raise Direction(404, f"No event object E{head_id} — open FEED and pick a headline.")
    return head_id


def race_id(session: Session, ref: str) -> str:
    """`AZ-SEN-2026` as-is; `AZ-SEN` or `AZ` -> that state's latest-cycle race."""
    ref = ref.strip().upper()
    ids = list(session.scalars(select(Race.id).order_by(Race.cycle.desc(), Race.id)))
    if ref in ids:
        return ref
    state = ref.split("-")[0]
    office = ref.split("-")[1] if "-" in ref else None
    matches = [
        r for r in ids
        if r.split("-")[0] == state and (office is None or r.split("-")[1] == office)
    ]
    if matches:
        return matches[0]
    raise Direction(
        404, f"No race {ref} — the MVP covers these Senate races:",
        [Option(label=r, command=f"RACE {r}") for r in sorted(ids)],
    )


def entity_id(session: Session, ref: str) -> int:
    """An entity's numeric ID, its canonical ID (`bioguide:M001153`), or a name mention."""
    ref = ref.strip()
    if ref.isdigit():
        if session.get(Entity, int(ref)) is None:
            raise Direction(404, f"No entity {ref} — look it up by name, e.g. ENT MURKOWSKI.")
        return int(ref)
    if ":" in ref:
        # The terminal upper-cases what it sends; canonical IDs mix case (`bioguide:M001153`).
        found = session.scalar(
            select(Entity.id).where(func.lower(Entity.canonical_id) == ref.lower())
        )
        if found is None:
            raise Direction(404, f"No entity {ref} — look it up by name, e.g. ENT MURKOWSKI.")
        return found
    r = resolve(session, ref, list(EntityType))
    if r.entity_id is not None:
        return r.entity_id
    if not r.candidates:
        raise Direction(404, f"No entity matches {ref} — try a surname or a FRED series ID.")
    raise Direction(
        409, f"{ref} does not resolve to one entity — pick the closest match:",
        [Option(label=f"{c.name} ({c.canonical_id})", command=f"ENT {c.entity_id}")
         for c in r.candidates],
    )


def topic(ref: str, command_prefix: str = "") -> Topic:
    """A topic slug, or any whole word of one: TARIFFS -> trade_tariffs. Options run
    `command_prefix` + the topic."""
    word = ref.strip().lower().replace("-", "_")
    try:
        return Topic(word)
    except ValueError:
        pass
    matches = [
        t for t in Topic
        if word in t.value.split("_") or (len(word) >= 4 and t.value.startswith(word))
    ]
    if len(matches) == 1:
        return matches[0]
    options = matches or list(Topic)
    raise Direction(
        409 if matches else 404,
        f"{ref} matches several topics — pick one:" if matches
        else f"No topic {ref} — use one of:",
        [Option(label=t.value, command=f"{command_prefix}{t.value.upper()}") for t in options],
    )
