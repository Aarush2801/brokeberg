from typing import Any

import pytest
from extract_docs import bill, vote, x_post
from pydantic import ValidationError
from sqlalchemy.orm import Session

from brokeberg.extract.doc import ExtractState, SourceDoc
from brokeberg.extract.entities import MentionLLM, MentionsLLM, entities
from brokeberg.extract.relationships import (
    RelationLLM,
    RelationsLLM,
    relationships,
)
from brokeberg.taxonomy import EdgeType


def _run(db: Session, doc: SourceDoc, fake_llm: Any) -> ExtractState:
    state = ExtractState(session=db)
    state.outputs["entities"] = entities(doc, state)
    state.outputs["relationships"] = relationships(doc, state)
    return state


def _cids(state: ExtractState) -> dict[int, str]:
    return {
        e.entity_id: e.canonical_id  # type: ignore[misc]
        for e in state.outputs["entities"].resolved  # type: ignore[attr-defined]
    }


def test_vote_edges_from_payload(seeded_db: Session, fake_llm: Any) -> None:
    fake_llm.set(MentionsLLM, MentionsLLM(mentions=[]))
    state = _run(seeded_db, vote(), fake_llm)
    cids = _cids(state)
    edges = {
        (cids[r.src_entity], r.relation, cids[r.dst_entity])
        for r in state.outputs["relationships"].relations  # type: ignore[attr-defined]
    }
    assert edges == {
        ("bioguide:M001153", EdgeType.VOTED_FOR, "bill:119-hr-9340"),
        ("bioguide:O000174", EdgeType.VOTED_AGAINST, "bill:119-hr-9340"),
    }  # 'Not Voting' yields no edge
    assert RelationsLLM not in fake_llm.schemas_called()


def test_sponsor_proposes_bill(seeded_db: Session, fake_llm: Any) -> None:
    fake_llm.set(MentionsLLM, MentionsLLM(mentions=[]))
    state = _run(seeded_db, bill(), fake_llm)
    cids = _cids(state)
    rels = state.outputs["relationships"].relations  # type: ignore[attr-defined]
    assert [(cids[r.src_entity], r.relation, cids[r.dst_entity]) for r in rels] == [
        ("bioguide:O000174", EdgeType.PROPOSES, "bill:119-s-877")
    ]


def test_llm_edges_filtered(seeded_db: Session, fake_llm: Any) -> None:
    fake_llm.set(
        MentionsLLM,
        MentionsLLM(
            mentions=[
                MentionLLM.model_validate(
                    {"mention": "Sen. Chuck Schumer", "entity_type": "Politician",
                     "role": "target", "span": "Sen. Chuck Schumer should", "confidence": 0.9}
                )
            ]
        ),
    )

    def respond(prompt: str) -> RelationsLLM:
        ids = sorted(_ids)
        a, b = ids[0], ids[1]
        span = "Sen. Chuck Schumer should bring the repeal to the floor."
        return RelationsLLM(
            relations=[
                RelationLLM(src_entity=a, relation=EdgeType.RESPONDS_TO, dst_entity=b,
                            rationale="r", span=span, confidence=0.8),
                RelationLLM(src_entity=a, relation=EdgeType.VOTED_FOR, dst_entity=b,
                            rationale="r", span=span, confidence=0.8),  # payload-only type
                RelationLLM(src_entity=a, relation=EdgeType.SUPPORTS, dst_entity=b,
                            rationale="r", span="not in the doc", confidence=0.8),
                RelationLLM(src_entity=a, relation=EdgeType.SUPPORTS, dst_entity=a,
                            rationale="r", span=span, confidence=0.8),  # self loop
            ]
        )

    _ids: set[int] = set()
    fake_llm.set(RelationsLLM, respond)
    state = ExtractState(session=seeded_db)
    state.outputs["entities"] = entities(x_post(), state)
    _ids.update(_cids(state))
    out = relationships(x_post(), state)
    assert [(r.relation, r.method) for r in out.relations] == [(EdgeType.RESPONDS_TO, "llm")]


def test_causes_is_not_an_edge_type() -> None:
    with pytest.raises(ValidationError):
        RelationLLM.model_validate(
            {"src_entity": 1, "relation": "CAUSES", "dst_entity": 2, "rationale": "r",
             "span": "s", "confidence": 0.5}
        )
