from typing import Any

from extract_docs import bill, x_post
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brokeberg.db.models import Entity, ReviewKind
from brokeberg.extract.doc import ExtractState
from brokeberg.extract.entities import MentionLLM, MentionsLLM, entities
from brokeberg.taxonomy import EntityType


def _m(mention: str, span: str, etype: str = "Politician", conf: float = 0.9) -> MentionLLM:
    return MentionLLM.model_validate(
        {"mention": mention, "entity_type": etype, "role": "target", "span": span,
         "confidence": conf}
    )


def test_seeded_senator_resolves_and_author_comes_from_connector(
    seeded_db: Session, fake_llm: Any
) -> None:
    fake_llm.set(
        MentionsLLM,
        MentionsLLM(mentions=[_m("Sen. Chuck Schumer", "Sen. Chuck Schumer should bring")]),
    )
    out = entities(x_post(), ExtractState(session=seeded_db))
    by_cid = {e.canonical_id: e for e in out.resolved}
    assert by_cid["bioguide:M001153"].role == "author"
    assert by_cid["bioguide:M001153"].method == "connector"
    assert by_cid["bioguide:S000148"].method == "exact"
    assert all(e.span for e in out.entities)


def test_unresolvable_actor_goes_to_review_not_entities(
    seeded_db: Session, fake_llm: Any
) -> None:
    doc = x_post("Sen. Nobody Fakename says tariffs must end.")
    fake_llm.set(MentionsLLM, MentionsLLM(mentions=[_m("Sen. Nobody Fakename", "Nobody Fakename")]))
    before = seeded_db.scalar(select(func.count()).select_from(Entity))
    state = ExtractState(session=seeded_db)
    out = entities(doc, state)
    assert [e.entity_id for e in out.entities if e.mention == "Sen. Nobody Fakename"] == [None]
    assert [(r.kind, r.mention) for r in state.review] == [
        (ReviewKind.UNRESOLVED_MENTION, "Sen. Nobody Fakename")
    ]
    assert seeded_db.scalar(select(func.count()).select_from(Entity)) == before


def test_ungrounded_mention_is_dropped(seeded_db: Session, fake_llm: Any) -> None:
    fake_llm.set(MentionsLLM, MentionsLLM(mentions=[_m("Sen. Jon Ossoff", "Ossoff agreed")]))
    state = ExtractState(session=seeded_db)
    out = entities(x_post(), state)
    assert "bioguide:O000174" not in {e.canonical_id for e in out.entities}
    assert state.review == []


def test_bill_item_mints_the_bill_node_from_payload(seeded_db: Session, fake_llm: Any) -> None:
    fake_llm.set(MentionsLLM, MentionsLLM(mentions=[]))
    out = entities(bill(), ExtractState(session=seeded_db))
    roles = {(e.canonical_id, e.role) for e in out.resolved}
    assert ("bioguide:O000174", "sponsor") in roles
    assert ("bill:119-s-877", "subject") in roles
    node = seeded_db.scalar(select(Entity).where(Entity.canonical_id == "bill:119-s-877"))
    assert node is not None and node.entity_type == EntityType.POLICY_BILL
    assert node.name == "S. 877 (119th): Lower Grocery Prices Act"


def test_llm_mention_of_freshly_minted_bill_resolves(seeded_db: Session, fake_llm: Any) -> None:
    from brokeberg.ids.resolve import resolve

    resolve(seeded_db, "S. 877", EntityType.POLICY_BILL)  # warm the alias cache before minting
    fake_llm.set(
        MentionsLLM,
        MentionsLLM(mentions=[_m("S. 877", "S. 877 (119th Congress)", "Policy_Bill")]),
    )
    state = ExtractState(session=seeded_db)
    out = entities(bill(), state)
    llm_hits = [e for e in out.entities if e.method != "connector"]
    assert [e.canonical_id for e in llm_hits] == ["bill:119-s-877"]
    assert state.review == []
