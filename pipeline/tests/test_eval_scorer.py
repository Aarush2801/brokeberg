import pytest

from brokeberg.eval.golden import Expected, ExpectedStance, load
from brokeberg.eval.run import scored_entities
from brokeberg.eval.score import Predicted, score
from brokeberg.extract.entities import LinkedEntity
from brokeberg.taxonomy import EntityType, EventType, Stance, Topic

T, H = Topic.TRADE_TARIFFS, Topic.HOUSING


def test_perfect_prediction() -> None:
    gold = Expected(
        relevant=True, event_type=EventType.STATEMENT, entities=["fips:02"], topics=[T],
        stances=[ExpectedStance(canonical_id="bioguide:X", topic=T, position=Stance.OPPOSE)],
    )
    pred = Predicted(
        relevant=True, event_type=EventType.STATEMENT, entities={"fips:02"}, topics={T},
        stances={("bioguide:X", T): Stance.OPPOSE},
    )
    m = score([(gold, pred)])
    assert all(m[k] == 1.0 for k in m if isinstance(m[k], float))


def test_partial_metrics() -> None:
    pairs = [
        (
            Expected(relevant=True, event_type=EventType.STATEMENT, entities=["a", "b"],
                     topics=[T, H],
                     stances=[ExpectedStance(canonical_id="a", topic=T,
                                             position=Stance.STRONGLY_OPPOSE)]),
            Predicted(relevant=True, event_type=EventType.CONTROVERSY, entities={"a", "c"},
                      topics={T}, stances={("a", T): Stance.LEAN_OPPOSE, ("b", H): Stance.SUPPORT}),
        ),
        (Expected(relevant=False), Predicted(relevant=False)),  # correct drop
        (Expected(relevant=False), Predicted(relevant=True)),  # missed drop
    ]
    m = score(pairs)
    assert m["gate.accuracy"] == pytest.approx(2 / 3)
    assert m["gate.drop_precision"] == 1.0 and m["gate.drop_recall"] == 0.5
    assert m["event_type.accuracy"] == 0.0
    assert m["entities.precision"] == 0.5 and m["entities.recall"] == 0.5
    assert m["topics.precision"] == 1.0 and m["topics.recall"] == 0.5
    assert m["stance.precision"] == 0.5 and m["stance.recall"] == 1.0
    assert m["stance.position_accuracy"] == 0.0  # strongly_oppose vs lean_oppose
    assert m["stance.direction_accuracy"] == 1.0  # both oppose


def test_wrongly_dropped_item_counts_as_misses() -> None:
    m = score([(Expected(relevant=True, entities=["a"], topics=[T]), Predicted(relevant=False))])
    assert m["entities.recall"] == 0.0 and m["topics.recall"] == 0.0


def test_golden_file_loads_and_is_well_formed() -> None:
    items = load()
    assert 30 <= len(items) <= 50
    assert any(not i.expected.relevant for i in items)  # has negatives
    for i in items:
        for s in i.expected.stances:
            assert s.canonical_id in i.expected.entities or s.canonical_id in i.resolved, i.id


def _linked(cid: str, role: str) -> LinkedEntity:
    return LinkedEntity(
        mention=cid, entity_id=hash(cid) % 1000, canonical_id=cid,
        entity_type=EntityType.POLITICIAN, role=role, span=cid, confidence=1.0, method="connector",
    )


def test_sponsor_tagged_actor_too_is_not_scored() -> None:
    # A bill's sponsor comes back as both `sponsor` and `actor`; gold never lists the sponsor.
    scored, excluded = scored_entities([
        _linked("bioguide:W000790", "sponsor"),
        _linked("bioguide:W000790", "actor"),
        _linked("bill:119-s-5690", "subject"),
    ])
    assert scored == {"bill:119-s-5690"}
    assert excluded == {"bioguide:W000790"}


def test_non_structural_entities_are_scored() -> None:
    scored, excluded = scored_entities([
        _linked("bioguide:A", "actor"),
        _linked("bioguide:B", "author"),
        _linked("fips:02", "target"),
    ])
    assert scored == {"bioguide:A", "fips:02"} and excluded == set()
