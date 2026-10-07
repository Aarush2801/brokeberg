# CLAUDE.md — Brokeberg

> This file loads every session. Keep it lean. The per-day task briefs live in `tasks/`.
> At the start of a work session, tell me which day file to read, e.g. *"Read tasks/day-1-schema.md and do it."*

## What we're building

Brokeberg is a low-cost political-economic intelligence terminal. It continuously ingests
government, economic, and election data, uses an LLM to turn raw text into **structured events,
entities, and relationships** in a knowledge graph, and serves a Bloomberg-style text terminal
that answers "what changed and what's connected" — not "what do I already know to ask."

**MVP scope: US federal + Senate only.** No House, governors, state legislatures, or markets-as-
asset-class yet. Depth on one slice beats breadth. Do not expand scope without being told.

## GOLDEN RULES (never violate — these are the product)

1. **Canonical IDs, never name strings.** Every entity resolves to a stable ID (bioguide / FEC /
   FRED series / state FIPS). The graph is built on IDs. "Senator Reyes" is a *mention*; it must
   link to an ID or go to the review queue. Never create a node keyed by a display name.
2. **Provenance on every claim.** Every stored fact carries source URL + a verbatim span + a
   timestamp + a confidence. No span → reject the claim. If you can't ground it, don't store it.
3. **The LLM is the structuring layer, not the source of truth.** It extracts, links, classifies,
   and synthesizes. It is NOT the database, NOT the retriever of record, NOT the arbiter of facts.
4. **No LLM in deterministic ranking.** Evidence selection, salience, and clustering thresholds are
   code. The LLM only labels and breaks ties. Keep it off the critical ranking path.
5. **Confidence per field.** Everything extracted gets a 0–1 confidence. Low-confidence → review queue.
6. **Correlation, never causation.** Edges say `CORRELATES_WITH`, never `CAUSES`. The UI frames
   co-occurrence and timelines, never causal claims.
7. **Evals from Day 3 on.** Any change to an extraction prompt is measured against the golden set
   before it's accepted. Never "improve" a prompt without running `make eval`.
8. **Idempotency.** Every raw item has a content hash. Never reprocess or double-insert the same item.

## Architecture

Two writers, one graph:
- **Streaming pipeline (MVP):** scheduled, high-volume, cheap-per-item. Continuous ingestion → extract
  → cluster → verify → graph. This is what we build in 7 phases.
- **Deep-research agent (v2, not now):** on-demand, looping, expensive. Investigates a question.

Data flow (streaming):
```
APIs → ingest (normalize to canonical IDs) → raw to S3/local
     → extract DAG (LLM) → cluster/dedup (embeddings) → verify → write graph (Aurora+pgvector)
query: question → retrieve (pgvector + SQL) → LLM synthesizes over retrieved records → answer + citations
```

Dev runs locally (Docker Postgres + pgvector, Anthropic API). Deploy runs on AWS
(EventBridge → Lambda → S3 → Aurora + pgvector → Bedrock → API Gateway → Next.js on Vercel).
**Build and test everything locally first; AWS is Day 7.**

## Repo layout

```
brokeberg/
  CLAUDE.md                 # this file
  PLAN.md                   # full explanation of the build
  SETUP.md                  # one-time setup
  tasks/day-0..7.md         # per-session task briefs
  docker-compose.yml        # local postgres + pgvector
  .env.example / .env       # secrets (NEVER commit .env)
  pipeline/                 # Python
    pyproject.toml
    brokeberg/
      taxonomy.py           # enums — SINGLE SOURCE OF TRUTH for all controlled vocab
      config.py             # env, settings
      db/                   # models, migrations (alembic), session
      ids/                  # canonical-ID resolvers (bioguide, fec, fred, fips)
      llm/                  # model interface: anthropic (dev) | bedrock (prod)
      embed/                # embedding interface: local bge (dev) | titan v2 (prod)
      ingest/               # one connector per source, common interface
      extract/              # DAG passes 0-5
      cluster/              # pass 6
      verify/               # pass 7
      graph/                # edges, materialized views, salience
      eval/                 # golden set + scorer
    tests/
  web/                      # Next.js terminal UI (seed from the mockup)
  infra/                    # AWS CDK (Python) — Day 7 only
```

## Stack (decided — do not substitute without asking)

- **Python 3.11+**, SQLAlchemy 2.0 + Alembic, `psycopg[binary]`, `pgvector`, `pydantic` v2, `httpx`,
  `tenacity` (retries), `vcrpy` (recorded fixtures), `pytest`, `python-dotenv`.
- **Postgres 16 + pgvector** (Docker image `pgvector/pgvector:pg16`). Aurora Serverless v2 in prod.
- **LLM:** Claude Sonnet via `anthropic` SDK (dev) or Bedrock (prod), behind `llm/`. Default model Sonnet.
- **Embeddings (1024-dim, same dev & prod):** `BAAI/bge-large-en-v1.5` local via `sentence-transformers`
  (dev), Bedrock Titan Text Embeddings v2 (prod). The pgvector column is `vector(1024)`.
- **Scraping:** `httpx` + `selectolax`/`beautifulsoup4`; `feedparser` for RSS. Respect robots.txt.
- **Web:** Next.js (App Router) + plain CSS (the terminal look is already built). Host on Vercel.
- **Infra:** AWS CDK (Python).

## Canonical IDs

- Members of Congress → **bioguide ID** (`bioguide.congress.gov`)
- Candidates / committees → **FEC candidate ID / committee ID** (via api.data.gov)
- Economic series → **FRED series ID** (e.g., `CPIAUCSL`)
- Geography → **state FIPS** (+ district)
- Races → composite `STATE-OFFICE-CYCLE` (e.g., `AZ-SEN-2026`), plus Ballotpedia slug

An incumbent who is both a legislator and a candidate is **one node** (bioguide primary, FEC in aliases).

## Taxonomy (source of truth: `pipeline/brokeberg/taxonomy.py`)

- **event_type:** legislative_action, executive_action, statement, economic_release, judicial_action,
  poll_release, campaign_finance_filing, election_result, controversy, nomination, regulatory_action, geopolitical
- **topic / policy_area:** inflation_cost_of_living, taxation, trade_tariffs, immigration, healthcare,
  energy_climate, labor_jobs, housing, monetary_policy, fiscal_debt, foreign_policy_defense,
  social_abortion, crime_justice, tech_ai_regulation, education, agriculture
- **stance:** strongly_support, support, lean_support, neutral_unclear, lean_oppose, oppose, strongly_oppose
  (+ `intensity` 0–1)
- **entity_type:** Politician, Agency, Committee, Party, Candidate, Race, Office, Jurisdiction,
  EconomicIndicator, Industry, Company, InterestGroup_PAC, Country, Policy_Bill
- **jurisdiction_level:** federal, state, district, local
- **race_type:** Senate, House, Governor, President, ballot_measure
- **race_rating:** {Safe, Likely, Lean, Tossup} × {D, R}
- **source_type / trust_tier:** government_primary(T1), official_statement(T1), data_release(T1),
  press_release(T2), poll(T2), news(T3), social_post(T4)
- **edge_type:** SUPPORTS, OPPOSES, PROPOSES, VOTED_FOR, VOTED_AGAINST, AFFECTS, EXPOSED_TO,
  LOCATED_IN, COMPETES_IN, ENDORSES, FUNDED_BY, RESPONDS_TO, CORRELATES_WITH  (never CAUSES)
- **verification_status:** unverified, single_source, corroborated, contradicted, fact_checked

## DB spine (see day-1 for full DDL)

`raw_items` · `events` · `entities` · `event_sources` (provenance) · `event_entities` (role+stance+span)
· `edges` · `indicators` · `poll_averages` · `races` · `race_ratings_history` · `event_embeddings` (vector(1024))

Every event stores both `event_time` (when it happened) and `ingest_time` (when we saw it).

## Extraction DAG (see day-3)

0 normalize+gate → 1 event core → 2 entity extract+link → 3 classify → 4 stance → 5 relationships
→ 6 cluster/link → 7 verify → 8 materialize. Each pass is a separate, separately-tested function with
strict JSON-schema (pydantic) output. Cheap model where possible; big model only for synthesis/tiebreak.

## Commands

```
make up            # docker compose up postgres+pgvector
make migrate       # alembic upgrade head
make test          # pytest (uses recorded fixtures, no live API calls)
make eval          # run extraction eval against the golden set, print P/R
make lint          # ruff + mypy
make ingest-once   # run one ingestion cycle locally
make web           # cd web && npm run dev
```

## Claude Code working rules (also saves Pro tokens)

- **Use plan mode for anything structural.** Show the plan, wait for approval, then build.
- **One task per session.** `/clear` between unrelated tasks. `/compact` when context grows.
- **Write tests alongside code**, not after. Tests are the guardrail that keeps you honest.
- **Commit at each phase boundary** with the message from the day file. Small, revertible commits.
- **Never call live external APIs in tests** — use vcrpy fixtures.
- **Default to Sonnet.** Don't reach for larger context than the task needs — big context burns the
  Pro session window faster.
- **Stay in scope.** If a task tempts you to touch another module, stop and note it instead.

## Current focus

> Set this line each session: **ACTIVE = tasks/day-0-setup.md**
