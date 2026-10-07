from typing import Any

import pytest
from extract_docs import WHEN, x_post
from pydantic import ValidationError
from sqlalchemy.orm import Session

from brokeberg.extract.doc import ExtractState, UngroundedError
from brokeberg.extract.event_core import EventCoreLLM, event_core
from brokeberg.taxonomy import EventType


def _core(**over: Any) -> EventCoreLLM:
    base: dict[str, Any] = {
        "event_type": "statement",
        "headline": "Murkowski says she will vote against extending lumber tariffs",
        "actor_mention": "@LisaMurkowski",
        "action": "will vote against",
        "object": "extending lumber tariffs",
        "event_time": None,
        "jurisdiction": "Alaska",
        "span": "I will vote against extending them.",
        "confidence": 0.9,
    }
    return EventCoreLLM.model_validate(base | over)


def test_event_core_valid(db_session: Session, fake_llm: Any) -> None:
    fake_llm.set(EventCoreLLM, _core())
    out = event_core(x_post(), ExtractState(session=db_session))
    assert out.event_type == EventType.STATEMENT
    assert out.jurisdiction_id == "fips:02"
    assert out.event_time == WHEN  # the source timestamp wins
    assert out.span in x_post().text


def test_federal_jurisdiction(db_session: Session, fake_llm: Any) -> None:
    fake_llm.set(EventCoreLLM, _core(jurisdiction="federal"))
    assert event_core(x_post(), ExtractState(session=db_session)).jurisdiction_id == "federal"


def test_ungrounded_span_is_rejected(db_session: Session, fake_llm: Any) -> None:
    fake_llm.set(EventCoreLLM, _core(span="Murkowski blasted the tariffs"))
    with pytest.raises(UngroundedError):
        event_core(x_post(), ExtractState(session=db_session))


def test_enum_and_range_enforced() -> None:
    with pytest.raises(ValidationError):
        _core(event_type="press_conference")
    with pytest.raises(ValidationError):
        _core(confidence=1.5)


def test_low_confidence_goes_to_review(db_session: Session, fake_llm: Any) -> None:
    fake_llm.set(EventCoreLLM, _core(confidence=0.3))
    state = ExtractState(session=db_session)
    event_core(x_post(), state)
    assert [r.field for r in state.review] == ["event_core"]
