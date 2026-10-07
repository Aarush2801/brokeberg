from typing import Any

from extract_docs import bill, off_topic
from sqlalchemy.orm import Session

from brokeberg.db.models import ExtractionStatus
from brokeberg.extract.doc import ExtractState
from brokeberg.extract.gate import GateResult, gate
from brokeberg.extract.run import run_passes


def test_off_topic_item_is_dropped_with_reason(db_session: Session, fake_llm: Any) -> None:
    fake_llm.set(GateResult, GateResult(relevant=False, reason="sports result", confidence=0.97))
    ex = run_passes(db_session, off_topic())
    assert ex.status == ExtractionStatus.DROPPED
    assert ex.dropped_reason == "sports result"
    assert list(ex.state.outputs) == ["gate"]  # nothing past the gate ran
    assert ex.state.review == []


def test_unsure_drop_goes_to_review(db_session: Session, fake_llm: Any) -> None:
    fake_llm.set(GateResult, GateResult(relevant=False, reason="maybe sports", confidence=0.4))
    ex = run_passes(db_session, off_topic())
    assert [r.field for r in ex.state.review] == ["gate"]


def test_in_scope_sources_skip_the_llm(db_session: Session, fake_llm: Any) -> None:
    out = gate(bill(), ExtractState(session=db_session))
    assert out.relevant and out.confidence == 1.0
    assert fake_llm.calls == []


def test_gate_uses_cheap_model(db_session: Session, fake_llm: Any) -> None:
    from brokeberg.config import get_settings

    fake_llm.set(GateResult, GateResult(relevant=True, reason="x", confidence=0.9))
    gate(off_topic(), ExtractState(session=db_session))
    assert fake_llm.calls[0][2] == get_settings().llm_model_cheap
