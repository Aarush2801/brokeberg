# Day 5 — Verification, graph & elections

> Load: `CLAUDE.md`, this file. Selection ≠ verification. This phase grounds claims against truth and
> makes elections first-class.

## Objective
Add the verification layer, materialize the typed graph edges, wire event→race linkage, and build the
rollup views the terminal reads (feed, event, race dossier, entity dossier, stance timeline).

## Build

### 1. Verification (`verify/`)
- `corroborate.py` — count independent sources per event (distinct source_type/domain). ≥2 →
  `corroborated`; exactly 1 → `single_source`. Weight by trust tier.
- `numeric.py` — for events with a numeric economic claim, check against `indicators` (FRED/BLS). Match
  within tolerance → ok; mismatch → flag + lower confidence.
- `contradict.py` — compare a new stance for (entity, topic) against the latest stored one; material flip →
  `contradicted` flag on the event (surface both, don't overwrite).
- Write `verification_status` back onto the event; route low-confidence/contradicted to the review queue.

### 2. Graph edges (`graph/edges.py`)
Persist the typed edges from extraction pass 5, deduped, with rationale + confidence + source event.
Build helper queries for one-hop neighborhood of an entity.

### 3. Election linkage (`graph/elections.py`)
For each event, compute affected races: `topic ∈ race.salient_topics` AND
`event.jurisdiction intersects race.state_fips` AND `race.rating ∈ {Lean, Tossup}`.
Store as edges (`event -AFFECTS-> race`) **with rationale + confidence** — never a bare link.

### 4. Rollup views (`graph/views.py` + SQL/materialized views)
- `feed(limit)` — salience-ranked events:
  `salience = w1·recency_decay(event_time) + w2·log(1+source_count) + w3·entity_importance
   + w4·verification_bonus + w5·election_proximity`. Weights in config.
- `event_object(id)` — full object incl. affected_elections + sources.
- `race_dossier(id)` — rating + rating history + candidates/finance + poll avg + linked events.
- `entity_dossier(id)` — stance summary + recent events + one-hop relationships.
- `stance_timeline(entity_id, topic)` — ordered grounded stances with intensity.

## Guardrails / tests
- `tests/test_verify.py`: single-source event → `single_source`; a post claiming a wrong CPI number →
  numeric flag; a stance flip → `contradicted`.
- `tests/test_elections.py`: an inflation event in a Tossup state links to that race with a rationale;
  a Safe-seat state does not link.
- Views return correctly ordered, provenance-bearing rows.

## Definition of done
`make test` green; querying `feed`, `event_object`, `race_dossier`, `entity_dossier`, `stance_timeline`
returns correct, sourced results from the fixture data.

## Commit
`feat(graph): verification layer, typed edges, event→race linkage, rollup views`
