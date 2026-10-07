from typing import Any

import pytest
from extract_docs import bill, vote, x_post
from sqlalchemy.orm import Session

from brokeberg.extract.classify import Classification
from brokeberg.extract.doc import ExtractState, SourceDoc
from brokeberg.extract.entities import MentionsLLM, entities
from brokeberg.extract.stance import StanceLLM, StancesResult, stance
from brokeberg.taxonomy import Stance, Topic


def _state(db: Session, doc: SourceDoc, fake_llm: Any) -> ExtractState:
    fake_llm.set(MentionsLLM, MentionsLLM(mentions=[]))
    state = ExtractState(session=db)
    state.outputs["entities"] = entities(doc, state)
    state.outputs["classify"] = Classification(
        topics=[Topic.TRADE_TARIFFS], policy_areas=[], jurisdiction_level="federal",
        election_relevance=0.1, confidence=0.9,
    )
    return state


def _s(entity_id: int, span: str, topic: Topic = Topic.TRADE_TARIFFS) -> StanceLLM:
    return StanceLLM(
        entity_id=entity_id, topic=topic, position=Stance.OPPOSE, intensity=0.8,
        verbatim_span=span, confidence=0.9,
    )


def test_grounded_stance_kept_others_dropped(seeded_db: Session, fake_llm: Any) -> None:
    doc = x_post()
    state = _state(seeded_db, doc, fake_llm)
    author = state.outputs["entities"].resolved[0].entity_id  # type: ignore[attr-defined]
    fake_llm.set(
        StancesResult,
        StancesResult(
            stances=[
                _s(author, "I will vote against extending them."),  # kept
                _s(author, "I hate tariffs", Topic.HOUSING),  # topic not asked
                _s(author, "Murkowski opposes tariffs"),  # ungrounded
                _s(999_999, "I will vote against extending them."),  # unknown entity
            ]
        ),
    )
    out = stance(doc, state)
    assert [(s.entity_id, s.topic, s.position) for s in out.stances] == [
        (author, Topic.TRADE_TARIFFS, Stance.OPPOSE)
    ]


@pytest.mark.parametrize("make_doc", [bill, vote])
def test_bill_and_vote_items_skip_stance(
    seeded_db: Session, fake_llm: Any, make_doc: Any
) -> None:
    doc = make_doc()
    state = _state(seeded_db, doc, fake_llm)
    assert stance(doc, state).stances == []
    assert StancesResult not in fake_llm.schemas_called()
