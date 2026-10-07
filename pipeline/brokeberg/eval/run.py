"""Run the extraction passes over the golden set and report per-pass precision/recall.

`python -m brokeberg.eval.run [--ids a,b] [--verified-only] [--include-synthetic] [--save-baseline]`

Scores real items only by default. `--include-synthetic` adds the hand-written coverage items
(made-up quotes); such a run is never compared to or saved as the baseline.

Needs the seeded dev DB (entity resolution is part of what is measured) and a live LLM key.
Nothing is persisted: each item runs in a savepoint that is rolled back.
Exits non-zero if any metric regresses more than `TOLERANCE` against `baseline.json`.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from brokeberg.config import get_settings
from brokeberg.db.models import Entity, ExtractionStatus
from brokeberg.db.session import get_sessionmaker
from brokeberg.eval.golden import STRUCTURAL_ROLES, GoldenItem, load
from brokeberg.eval.score import Predicted, score
from brokeberg.extract.classify import Classification
from brokeberg.extract.doc import PROMPT_VERSION
from brokeberg.extract.entities import EntitiesResult
from brokeberg.extract.event_core import EventCore
from brokeberg.extract.gate import GateResult
from brokeberg.extract.run import Extraction, run_passes
from brokeberg.extract.stance import StancesResult
from brokeberg.ids.resolve import clear_cache
from brokeberg.taxonomy import EntityType

EVAL_DIR = Path(__file__).resolve().parent
BASELINE = EVAL_DIR / "baseline.json"
RESULTS_DIR = EVAL_DIR / "results"
TOLERANCE = 0.02  # a rate metric may drop at most this much vs. baseline


def to_predicted(ex: Extraction) -> Predicted:
    out = ex.state.outputs
    gate = out.get("gate")
    pred = Predicted(
        relevant=gate.relevant if isinstance(gate, GateResult) else True,
        failed=ex.status == ExtractionStatus.FAILED,
    )
    core = out.get("event_core")
    if isinstance(core, EventCore):
        pred.event_type = core.event_type
    ents = out.get("entities")
    cid_by_id: dict[int, str] = {}
    if isinstance(ents, EntitiesResult):
        for e in ents.resolved:
            assert e.entity_id is not None and e.canonical_id is not None
            cid_by_id[e.entity_id] = e.canonical_id
            if e.role not in STRUCTURAL_ROLES:
                pred.entities.add(e.canonical_id)
    cls = out.get("classify")
    if isinstance(cls, Classification):
        pred.topics = set(cls.topics)
    st = out.get("stance")
    if isinstance(st, StancesResult):
        pred.stances = {(cid_by_id[s.entity_id], s.topic): s.position for s in st.stances}
    return pred


def _item_report(item: GoldenItem, ex: Extraction, pred: Predicted) -> dict[str, Any]:
    gold = item.expected
    gold_st = {f"{s.canonical_id}|{s.topic}": str(s.position) for s in gold.stances}
    pred_st = {f"{k[0]}|{k[1]}": str(v) for k, v in pred.stances.items()}
    return {
        "id": item.id,
        "status": ex.status.value,
        "error": ex.error,
        "relevant": [gold.relevant, pred.relevant],
        "event_type": [gold.event_type, pred.event_type],
        "entities": {
            "missed": sorted(set(gold.entities) - pred.entities),
            "extra": sorted(pred.entities - set(gold.entities)),
        },
        "topics": {
            "missed": sorted(set(gold.topics) - pred.topics),
            "extra": sorted(pred.topics - set(gold.topics)),
        },
        "stances": {"gold": gold_st, "pred": pred_st},
        "review": [r.model_dump(mode="json") for r in ex.state.review],
    }


def evaluate(items: list[GoldenItem]) -> tuple[dict[str, float | int], list[dict[str, Any]]]:
    session = get_sessionmaker()()
    try:
        if not session.scalar(
            select(func.count()).select_from(Entity).where(
                Entity.entity_type == EntityType.POLITICIAN
            )
        ):
            sys.exit("no Politician entities: run `make seed` (and `make fetch-senators`) first")
        pairs, reports = [], []
        for n, item in enumerate(items, 1):
            savepoint = session.begin_nested()
            ex = run_passes(session, item.doc())
            savepoint.rollback()  # never persist eval runs (incl. any minted bill node)
            clear_cache()
            pred = to_predicted(ex)
            pairs.append((item.expected, pred))
            reports.append(_item_report(item, ex, pred))
            print(f"  [{n:>2}/{len(items)}] {item.id:<28} {ex.status.value}", file=sys.stderr)
        return score(pairs), reports
    finally:
        session.rollback()
        session.close()


def _fmt(v: float | int) -> str:
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def compare(metrics: dict[str, float | int], baseline: dict[str, Any] | None) -> list[str]:
    """Print the table; return the names of regressed metrics."""
    base = (baseline or {}).get("metrics", {})
    regressed = []
    print(f"\n{'metric':<28} {'value':>7} {'baseline':>9} {'delta':>7}")
    print("-" * 54)
    for k, v in metrics.items():
        b = base.get(k)
        delta = ""
        if isinstance(v, float) and isinstance(b, float):
            d = v - b
            delta = f"{d:+.3f}"
            if d < -TOLERANCE:
                regressed.append(k)
                delta += "  REGRESSED"
        print(f"{k:<28} {_fmt(v):>7} {_fmt(b) if b is not None else '-':>9} {delta:>7}")
    return regressed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ids", default=None, help="comma-separated golden ids to run")
    parser.add_argument("--verified-only", action="store_true")
    parser.add_argument(
        "--include-synthetic", action="store_true",
        help="also score synthetic items (report only; never a baseline)",
    )
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument(
        "--allow-unverified-baseline", action="store_true",
        help="save a baseline even though some labels are unverified",
    )
    args = parser.parse_args()

    if args.include_synthetic and args.save_baseline:
        sys.exit("a baseline is real items only; drop --include-synthetic")
    items = load()
    if not args.include_synthetic:
        items = [i for i in items if not i.synthetic]
    if args.ids:
        wanted = set(args.ids.split(","))
        items = [i for i in items if i.id in wanted]
    if args.verified_only:
        items = [i for i in items if i.verified]
    unverified = [i.id for i in items if not i.verified]
    if unverified:
        print(f"WARNING: {len(unverified)}/{len(items)} golden items are unverified; "
              "metrics are provisional.", file=sys.stderr)

    metrics, reports = evaluate(items)
    settings = get_settings()
    result = {
        "run_at": datetime.now(UTC).isoformat(),
        "prompt_version": PROMPT_VERSION,
        "models": {"default": settings.llm_model, "cheap": settings.llm_model_cheap},
        "items": [i.id for i in items],
        "include_synthetic": args.include_synthetic,
        "unverified": unverified,
        "metrics": metrics,
        "per_item": reports,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else None
    comparable = baseline is not None and baseline.get("items") == result["items"]
    if baseline is not None and not comparable:
        print("\n(baseline covers a different item set; deltas not checked)")
    regressed = compare(metrics, baseline if comparable else None)
    print(f"\nwrote {out.relative_to(EVAL_DIR.parents[1])}")
    failed = [r for r in reports if r["status"] == ExtractionStatus.FAILED.value]
    if failed:
        print(f"\nWARNING: {len(failed)} item(s) FAILED; metrics are not meaningful. First error:\n"
              f"  {failed[0]['id']}: {failed[0]['error']}", file=sys.stderr)

    if args.save_baseline:
        if failed:
            sys.exit("refusing to save a baseline from a run with failed items")
        if unverified and not args.allow_unverified_baseline:
            sys.exit("refusing to save a baseline with unverified labels "
                     "(verify them, or pass --allow-unverified-baseline)")
        BASELINE.write_text(json.dumps({k: result[k] for k in (
            "run_at", "prompt_version", "models", "items", "metrics")}, indent=2))
        print(f"saved baseline -> {BASELINE.name}")
    elif regressed or failed:
        sys.exit(f"REGRESSION vs baseline: {', '.join(regressed)}" if regressed
                 else "eval run had failed items")


if __name__ == "__main__":
    main()
