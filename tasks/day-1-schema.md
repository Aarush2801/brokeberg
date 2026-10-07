# Day 1 — Schema & canonical IDs

> Load: `CLAUDE.md`, this file. Use **plan mode** for the schema before writing migrations.
> This is the foundation — if the IDs or schema are wrong, every later phase inherits the error.

## Objective
The full DB spine as Alembic migrations + SQLAlchemy models, and the canonical-ID resolvers that turn a
code or mention into a stable ID. Seed the fixed reference data (Senate members, ~10 target races,
~20 FRED series).

## Deliverables

### 1. Schema (Alembic migration + models in `db/models.py`)
Tables (columns are the minimum; add sensibly, keep types tight):

- `raw_items(id, source, source_type, content_hash UNIQUE, url, payload_jsonb, fetched_at, event_time)`
- `entities(id, entity_type, canonical_id UNIQUE, name, aliases jsonb, importance float, meta jsonb)`
- `events(id, cluster_id, event_type, headline, what_happened, why_it_matters, event_time, ingest_time,
   confidence float, verification_status, topics text[], policy_areas text[], jurisdiction)`
- `event_sources(id, event_id→events, raw_item_id→raw_items, url, span text, trust_tier, claim text)`
- `event_entities(event_id→events, entity_id→entities, role, stance, intensity float, span text,
   confidence float, PRIMARY KEY(event_id, entity_id, role))`
- `edges(id, src_entity→entities, relation, dst_entity→entities, rationale, confidence float,
   event_id→events, created_at)`
- `indicators(series_id, source, asof date, value numeric, PRIMARY KEY(series_id, asof))`
- `races(id, state_fips, office, cycle, rating, salient_topics text[], fec_candidate_ids text[],
   ballotpedia_slug, meta jsonb)`   -- id = e.g. 'AZ-SEN-2026'
- `race_ratings_history(id, race_id→races, rater, rating, asof)`
- `poll_averages(id, race_id→races, value, meta jsonb, asof)`
- `event_embeddings(event_id→events PK, embedding vector(1024))`  -- pgvector, ivfflat/hnsw index later

Constraints: `content_hash` unique (idempotency); FK indexes; GIN index on `events.topics`.
Store **both** `event_time` and `ingest_time` on events.

### 2. Canonical-ID resolvers (`ids/`)
- `ids/bioguide.py` — resolve a member name/handle → bioguide ID (uses the seeded member table).
- `ids/fec.py` — candidate/committee name → FEC ID.
- `ids/fred.py` — validate/normalize a FRED series ID.
- `ids/fips.py` — state name/abbrev → FIPS.
- `ids/resolve.py` — `resolve(mention, entity_type) -> ResolveResult{entity_id|None, confidence, candidates}`.
  Strategy: exact alias match → fuzzy match (rapidfuzz) over `entities.aliases` → None (→ review queue).
  **Never** mint an entity from a raw name string here.

### 3. Seeds (`db/seed.py`, idempotent)
- Current US Senators as `entities` (type Politician) with bioguide IDs + alias lists (pull from
  Congress.gov member endpoint once; store).
- ~10 competitive Senate races as `races` rows (`AZ-SEN-2026`, `OH-SEN-2026`, …) with salient_topics.
- ~20 FRED series IDs registered (CPIAUCSL, CPILFESL, UNRATE, PAYEMS, DFF, DGS10, …).

## Guardrails / tests
- Migration up/down is clean (`alembic upgrade head` then `downgrade base`).
- `tests/test_ids.py`: known name → correct canonical ID; unknown → `None` with candidates listed.
- Seed is idempotent (run twice, same row count).

## Definition of done
`make migrate && make test` green; `psql` shows seeded senators, races, series.

## Commit
`feat(db): schema spine, canonical-id resolvers, reference seeds`
