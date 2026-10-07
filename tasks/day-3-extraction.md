# Day 3 — Extraction DAG + eval harness

> Load: `CLAUDE.md`, this file. This is the heart of the product. Build the eval harness TODAY, not later.
> Each pass is a separate function with a strict pydantic output schema. No mega-prompt.

## Objective
A multi-pass extraction pipeline that turns a `raw_item` into structured, span-grounded, canonical-ID-
linked records with per-field confidence — plus a golden set and scorer so every prompt change is measured.

## Passes (`extract/`)
Each pass: `def pass_n(item, state) -> PydanticModel`. Strict JSON via `llm.complete(..., schema=Model)`.
Cheap model by default; escalate only where needed.

0. `gate.py` — relevance classifier: political/economic? If not, drop (store a dropped-reason). Cheap.
1. `event_core.py` → `{event_type, actor_mention, action, object, event_time, jurisdiction, confidence}`.
2. `entities.py` — extract mentions, then **link each to a canonical ID via `ids.resolve`**. Unresolved →
   `review_queue` row, not a new entity. Output `[{mention, entity_id|None, role, span, confidence}]`.
3. `classify.py` → `{topics[], policy_areas[], jurisdiction_level, election_relevance (0–1)}` (multi-label).
4. `stance.py` — per (resolved actor, topic): `{position, intensity, verbatim_span, confidence}`.
   **No span → drop the stance.** Positions from the taxonomy enum only.
5. `relationships.py` → typed edges `[{src_entity, relation, dst_entity, rationale, confidence}]`.
   `CORRELATES_WITH` for economic links, never `CAUSES`.

`extract/run.py` chains 0→5 over a raw_item and persists partials with provenance. Idempotent on
`raw_item.content_hash`.

## Eval harness (`eval/`) — build this today
- `eval/golden/` — 30–50 hand-labeled items (seed from your own daily news list). Schema mirrors pass
  outputs: for each item, the correct event_type, entities (canonical IDs), topics, and stances.
- `eval/run.py` — runs passes over the golden items, computes **precision/recall per pass**
  (entity-linking accuracy, topic F1, stance accuracy, event_type accuracy). Prints a table; writes JSON.
- Rule: **no extraction-prompt change is accepted unless `make eval` is run and the numbers don't regress.**

## Guardrails / tests
- `tests/test_extract_*.py`: each pass validated against 2–3 fixture items (recorded LLM responses via
  vcrpy or a stubbed `llm.complete`). Assert schema validity, enum membership, span presence.
- A deliberately off-topic item is dropped by pass 0.
- An unresolvable actor goes to the review queue, not `entities`.

## Definition of done
`make eval` prints per-pass P/R on the golden set; `make test` green; one real sample item produces a
full structured record with spans + confidences in the DB.

## Commit
`feat(extract): 6-pass extraction DAG + golden-set eval harness`
