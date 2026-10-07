"""Per-pass metrics over (golden, predicted) pairs. Pure functions; no LLM, no DB.

- gate: accuracy, and precision/recall of *drops* (positive = "drop this item")
- event_type: accuracy over items both sides call relevant
- entities: micro P/R/F1 over (item, canonical_id)
- topics: micro P/R/F1 over (item, topic)
- stance: P/R/F1 on (item, actor, topic) pair detection; exact-position and direction
  (support / neutral / oppose) accuracy on matched pairs
"""

from dataclasses import dataclass, field

from brokeberg.eval.golden import Expected
from brokeberg.taxonomy import EventType, Stance, Topic

SUPPORT = {Stance.STRONGLY_SUPPORT, Stance.SUPPORT, Stance.LEAN_SUPPORT}
OPPOSE = {Stance.STRONGLY_OPPOSE, Stance.OPPOSE, Stance.LEAN_OPPOSE}


def direction(s: Stance) -> int:
    return 1 if s in SUPPORT else -1 if s in OPPOSE else 0


@dataclass
class Predicted:
    relevant: bool
    failed: bool = False
    event_type: EventType | None = None
    entities: set[str] = field(default_factory=set)
    topics: set[Topic] = field(default_factory=set)
    stances: dict[tuple[str, Topic], Stance] = field(default_factory=dict)


@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def add(self, gold: set[object], pred: set[object]) -> None:
        self.tp += len(gold & pred)
        self.fp += len(pred - gold)
        self.fn += len(gold - pred)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class Ratio:
    hit: int = 0
    n: int = 0

    def add(self, ok: bool) -> None:
        self.n += 1
        self.hit += int(ok)

    @property
    def value(self) -> float:
        return self.hit / self.n if self.n else 1.0


def score(pairs: list[tuple[Expected, Predicted]]) -> dict[str, float | int]:
    gate_acc, drops = Ratio(), PRF()
    etype, ents, topics, stance_pairs = Ratio(), PRF(), PRF(), PRF()
    pos_exact, pos_dir = Ratio(), Ratio()
    failed = 0

    for i, (gold, pred) in enumerate(pairs):
        failed += int(pred.failed)
        gate_acc.add(gold.relevant == pred.relevant)
        drops.add({i} if not gold.relevant else set(), {i} if not pred.relevant else set())
        if not gold.relevant:
            continue
        # A wrongly dropped (or failed) item counts as all-misses below.
        if pred.relevant and gold.event_type is not None:
            etype.add(gold.event_type == pred.event_type)
        ents.add({(i, e) for e in gold.entities}, {(i, e) for e in pred.entities})
        topics.add({(i, t) for t in gold.topics}, {(i, t) for t in pred.topics})
        gold_st = {(s.canonical_id, s.topic): s.position for s in gold.stances}
        stance_pairs.add({(i, k) for k in gold_st}, {(i, k) for k in pred.stances})
        for k in gold_st.keys() & pred.stances.keys():
            pos_exact.add(gold_st[k] == pred.stances[k])
            pos_dir.add(direction(gold_st[k]) == direction(pred.stances[k]))

    return {
        "items": len(pairs),
        "failed": failed,
        "gate.accuracy": gate_acc.value,
        "gate.drop_precision": drops.precision,
        "gate.drop_recall": drops.recall,
        "event_type.accuracy": etype.value,
        "entities.precision": ents.precision,
        "entities.recall": ents.recall,
        "entities.f1": ents.f1,
        "topics.precision": topics.precision,
        "topics.recall": topics.recall,
        "topics.f1": topics.f1,
        "stance.precision": stance_pairs.precision,
        "stance.recall": stance_pairs.recall,
        "stance.f1": stance_pairs.f1,
        "stance.position_accuracy": pos_exact.value,
        "stance.direction_accuracy": pos_dir.value,
    }
