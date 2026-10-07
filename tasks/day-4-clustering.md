# Day 4 — Clustering & the event object

> Load: `CLAUDE.md`, this file. LLM only breaks ties and writes titles — the clustering itself is code.

## Objective
Collapse many raw items about the same happening into one event cluster, and materialize the **event
object** (the core product primitive the terminal renders).

## Build (`cluster/`)
1. `embed_events.py` — embed each extracted item (headline + key spans) → `event_embeddings` (vector(1024)).
   Create the pgvector index (`ivfflat` with cosine, or `hnsw`); document the choice.
2. `cluster.py` — for a new item, find candidates by:
   - pgvector nearest-neighbors (cosine) **within a time window** (e.g., ±48h), AND
   - shared canonical-entity overlap (≥1 shared resolved entity).
   Decision: if top candidate's similarity ≥ T_high AND entity overlap → same cluster (attach as a new
   source). If below T_low → new cluster. In the ambiguous band → **one LLM tiebreak call**
   ("same underlying event? yes/no") — the only LLM use here. Thresholds in config, not hardcoded.
3. `event_object.py` — materialize/refresh an `events` row from its cluster:
   - `headline` + `what_happened` + `why_it_matters` (LLM synthesis over the cluster's grounded spans only)
   - roll up `event_entities` (dedup roles), `topics`, `policy_areas`
   - `political_reactions` = event_entities with a stance + span + source
   - `related_events` = edges to prior clusters (RESPONDS_TO / FOLLOWS)
   - `confidence` = aggregate; `verification_status` left for Day 5
   Synthesis must cite only stored spans — never introduce a fact not in the cluster.

## Guardrails / tests
- `tests/test_cluster.py`: three fixture items about one CPI release → one cluster; an unrelated item →
  its own cluster. Assert the tiebreak is only invoked in the ambiguous band.
- Re-running clustering is stable (idempotent; no duplicate clusters).
- `event_object` synthesis adds no entity or number absent from the cluster's spans (assert against inputs).

## Definition of done
Fixture corpus clusters correctly; `make test` green; one materialized event object in the DB with
reactions, topics, related events, and provenance.

## Commit
`feat(cluster): embedding+entity clustering, LLM tiebreak, materialized event object`
