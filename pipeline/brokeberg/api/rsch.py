"""RSCH: single-pass grounded answer over retrieved records.

Retrieval and ranking are code: pgvector kNN over member embeddings, plus the recent events of
entities the question names. The LLM writes claims over the numbered records only, each citing
the records it rests on; a claim whose numbers or named entities are not in its cited records is
dropped. The answer's confidence is computed from the cited sources, never by the model. If no
claim survives, the answer is a refusal: nothing is generated beyond the retrieved records.
"""

import re
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brokeberg import llm
from brokeberg.cluster.event_object import (
    TRUST_WEIGHT,
    Lexicon,
    load_lexicon,
    mentioned_entities,
    numbers,
)
from brokeberg.config import Settings, get_settings
from brokeberg.db.models import Event, EventEmbedding, EventEntity, HeadEvent
from brokeberg.embed import embed
from brokeberg.graph import views
from brokeberg.taxonomy import TrustTier

SYSTEM = (
    "You are the answer layer of a political-economic intelligence terminal. You state only what "
    "the given records state, cite every claim, never add outside knowledge, and never assert "
    "causation."
)

PROMPT = """Answer the question using ONLY the numbered records below. Each record is a verbatim
excerpt from a stored source, with the event it belongs to.

Rules:
- Each claim is one sentence. Every fact, name and number in it must appear in the records it
  cites. Copy numbers exactly as the records write them. No background, no outside knowledge.
- No causal claims: never say X caused, drove, or led to Y. Report what happened, when, and who
  said what. Things that happened together are only that.
- cited: the numbers of the records the claim rests on.
- At most 6 claims, most relevant first.
- If the records do not answer the question, return no claims and set insufficient to true.

<question>
{question}
</question>

<records>
{records}
</records>"""

REFUSAL = "Retrieved records don't answer this — name an entity, race or indicator, or open FEED."


class Claim(BaseModel):
    text: str = Field(min_length=1)
    cited: list[int]


class RschAnswer(BaseModel):
    claims: list[Claim]
    insufficient: bool


class Record(BaseModel):
    n: int
    event_id: int
    headline: str
    event_time: datetime
    event_confidence: float
    url: str
    span: str
    trust_tier: TrustTier
    speaker: str | None  # set for a stance record: whose statement the span is


class DroppedClaim(BaseModel):
    text: str
    problems: list[str]


class QueryResponse(BaseModel):
    question: str
    refused: bool
    message: str | None
    claims: list[Claim]
    sources: list[Record]
    confidence: float
    dropped_claims: list[DroppedClaim]


# --- retrieval ---------------------------------------------------------------------------------


def question_entities(question: str, lexicon: Lexicon) -> set[int]:
    """Entities the question names, case-insensitively (a terminal query is often all caps)."""
    folded = question.casefold()
    return {
        entity_id
        for surface, entity_id in lexicon.surfaces
        if surface.casefold() in folded
        and re.search(rf"(?<!\w){re.escape(surface)}(?!\w)", question, re.IGNORECASE)
    }


def retrieve(
    session: Session, question: str, lexicon: Lexicon, settings: Settings
) -> list[int]:
    """Head IDs to answer from: heads naming a question entity first, then by best member
    similarity, then newest; capped at `rsch_events`."""
    [vector] = embed([question])
    distance = EventEmbedding.embedding.cosine_distance(vector)
    sims: dict[int, float] = {}
    for head_id, d in session.execute(
        select(HeadEvent.id, distance)
        .join(Event, Event.cluster_id == HeadEvent.id)
        .join(EventEmbedding, EventEmbedding.event_id == Event.id)
        .order_by(distance, HeadEvent.id)
        .limit(settings.rsch_events * 4)
    ):
        sim = 1.0 - float(d)
        if sim >= settings.rsch_min_sim:
            sims[head_id] = max(sims.get(head_id, sim), sim)

    named = question_entities(question, lexicon)
    by_entity: set[int] = set()
    if named:
        by_entity = set(
            session.scalars(
                select(HeadEvent.id)
                .join(EventEntity, EventEntity.event_id == HeadEvent.id)
                .where(EventEntity.entity_id.in_(named))
                .group_by(HeadEvent.id)
                .order_by(func.max(HeadEvent.event_time).desc(), HeadEvent.id.desc())
                .limit(settings.rsch_events)
            )
        )

    times = {
        head_id: t
        for head_id, t in session.execute(
            select(HeadEvent.id, HeadEvent.event_time).where(
                HeadEvent.id.in_(set(sims) | by_entity)
            )
        )
    }
    ranked = sorted(
        times, key=lambda h: (h not in by_entity, -sims.get(h, 0.0), -times[h].timestamp(), h)
    )
    return ranked[: settings.rsch_events]


def build_records(session: Session, head_ids: list[int], settings: Settings) -> list[Record]:
    """Each head's sources (best trust first), then its stance spans; distinct, numbered."""
    out: list[Record] = []
    seen: set[tuple[str, str]] = set()
    for head_id in head_ids:
        obj = views.event_object(session, head_id)
        rows: list[tuple[str, str, TrustTier, str | None]] = [
            (s.url, s.span, s.trust_tier, None) for s in obj.sources
        ]
        rows += [(r.source_url, r.span, r.trust_tier, r.name) for r in obj.political_reactions]
        for url, span, tier, speaker in rows:
            if (url, span) in seen:
                continue
            seen.add((url, span))
            out.append(Record(
                n=len(out) + 1, event_id=obj.id, headline=obj.headline,
                event_time=obj.event_time, event_confidence=obj.confidence, url=url, span=span,
                trust_tier=tier, speaker=speaker,
            ))
    return out[: settings.rsch_max_records]


def render(r: Record) -> str:
    """The record exactly as the model sees it; claims are checked against this text."""
    who = f"; statement by {r.speaker}" if r.speaker else ""
    return (
        f"[{r.n}] (event E{r.event_id}, {r.event_time.date().isoformat()}, "
        f"\"{r.headline}\"{who}) {r.span}"
    )


# --- grounding ---------------------------------------------------------------------------------


def claim_problems(claim: Claim, records: dict[int, Record], lexicon: Lexicon) -> list[str]:
    """Every reason `claim` is not grounded in the records it cites; empty means keep."""
    if not claim.cited:
        return ["no citations"]
    if bad := sorted({c for c in claim.cited if c not in records}):
        return [f"cites records that were not retrieved: {bad}"]
    corpus = "\n".join(render(records[c]) for c in claim.cited)
    problems = []
    if extra := sorted(numbers(claim.text) - numbers(corpus)):
        problems.append(f"numbers not in cited records: {extra}")
    for surface, _ in mentioned_entities(claim.text, lexicon):
        if surface not in corpus:
            problems.append(f"names {surface!r}, which its cited records do not")
    return problems


def answer_confidence(kept: list[Claim], total: int, records: dict[int, Record]) -> float:
    """Mean over kept claims of their cited records' trust weight x event confidence, scaled by
    the share of the model's claims that survived grounding."""
    if not kept or not total:
        return 0.0
    per_claim = [
        sum(
            TRUST_WEIGHT[records[n].trust_tier] * records[n].event_confidence
            for n in c.cited
        ) / len(c.cited)
        for c in kept
    ]
    return round(sum(per_claim) / len(per_claim) * len(kept) / total, 3)


def answer(session: Session, question: str, settings: Settings | None = None) -> QueryResponse:
    settings = settings or get_settings()
    question = question.strip()
    lexicon = load_lexicon(session)
    records = build_records(session, retrieve(session, question, lexicon, settings), settings)

    def refuse(message: str, dropped: list[DroppedClaim] | None = None) -> QueryResponse:
        return QueryResponse(
            question=question, refused=True, message=message, claims=[], sources=records,
            confidence=0.0, dropped_claims=dropped or [],
        )

    if not records:
        return refuse(REFUSAL)
    try:
        out = llm.complete(
            PROMPT.format(question=question, records="\n".join(render(r) for r in records)),
            schema=RschAnswer, system=SYSTEM,
        )
    except llm.LLMOutputError:
        return refuse("The model returned an unusable answer — run the query again.")

    by_n = {r.n: r for r in records}
    kept: list[Claim] = []
    dropped: list[DroppedClaim] = []
    for c in out.claims:
        if problems := claim_problems(c, by_n, lexicon):
            dropped.append(DroppedClaim(text=c.text, problems=problems))
        else:
            kept.append(Claim(text=c.text, cited=sorted(set(c.cited))))
    if out.insufficient or not kept:
        return refuse(REFUSAL, dropped)
    return QueryResponse(
        question=question, refused=False, message=None, claims=kept, sources=records,
        confidence=answer_confidence(kept, len(out.claims), by_n), dropped_claims=dropped,
    )
