"""Pass 1: event core — what happened, who did it, when, where. Cheap model."""

from datetime import datetime

from pydantic import BaseModel, Field

from brokeberg import llm
from brokeberg.config import get_settings
from brokeberg.extract.doc import (
    SYSTEM,
    ExtractState,
    SourceDoc,
    UngroundedError,
    ground,
    render,
)
from brokeberg.ids import fips
from brokeberg.taxonomy import EventType

PROMPT = """Extract the single core event this item reports.

event_type, one of:
- legislative_action: bills introduced/advanced, votes, cloture, committee action
- executive_action: White House / president / executive orders
- statement: a politician or official stating a position (posts, speeches, press statements)
- economic_release: an official economic data release
- judicial_action, poll_release, campaign_finance_filing, election_result, controversy,
  nomination (incl. Senate votes on nominations), regulatory_action, geopolitical

Fields:
- headline: a neutral headline under 15 words. No causal claims.
- actor_mention: who acted, exactly as written in the document (null if none).
- action: the verb phrase; object: what it was done to (null if none).
- event_time: ISO-8601 if the document states when it happened, else null.
- jurisdiction: "federal", or the US state the event is about (name or 2-letter code), else null.
- span: the shortest verbatim excerpt that supports the event: one contiguous run of text
  copied exactly from a single line of the document. Never join separate lines.
- confidence: 0-1 that event_type and actor are right.

{doc}"""


class EventCoreLLM(BaseModel):
    event_type: EventType
    headline: str = Field(min_length=1)
    actor_mention: str | None
    action: str
    object: str | None
    event_time: datetime | None
    jurisdiction: str | None
    span: str
    confidence: float = Field(ge=0, le=1)


class EventCore(EventCoreLLM):
    # 'federal' or a state canonical ID ('fips:13'); None if the mention did not resolve.
    jurisdiction_id: str | None


def resolve_jurisdiction(mention: str | None) -> str | None:
    if not mention:
        return None
    if mention.strip().lower() == "federal":
        return "federal"
    return fips.canonical(mention)


def event_core(doc: SourceDoc, state: ExtractState) -> EventCore:
    out = llm.complete(
        PROMPT.format(doc=render(doc)),
        schema=EventCoreLLM,
        system=SYSTEM,
        model=get_settings().llm_model_cheap,
        max_tokens=1024,
    )
    if not ground(out.span, doc):
        raise UngroundedError(f"event span not found verbatim in source: {out.span!r}")
    core = EventCore(
        **out.model_dump(),
        jurisdiction_id=resolve_jurisdiction(out.jurisdiction),
    )
    # The source's own timestamp wins over the model's reading of the text.
    if doc.event_time is not None or core.event_time is None:
        core.event_time = doc.event_time
    state.flag_low_confidence(
        "event_core", core.headline, core.confidence, core.model_dump(mode="json")
    )
    return core
