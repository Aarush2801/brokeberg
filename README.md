# Brokeberg

A low-cost political-economic intelligence terminal. Brokeberg continuously ingests government,
economic, and election data, uses an LLM to turn raw text into **structured events, entities, and
relationships** in a knowledge graph, and serves a Bloomberg-style text terminal that answers
*"what changed, and what's connected to it"*. A search engine answers the questions you already know
to ask. Brokeberg does the structuring and aggregation ahead of time, so a query becomes cheap
retrieval over a graph where every fact carries its provenance.

**Scope:** US federal + Senate only (MVP).

---

## How it works

```
 Congress.gov ─┐
 Voteview ─────┤
 FRED / BLS ───┤   ingest            extract DAG (LLM)          cluster          verify          graph
 FEC ──────────┼─▶ normalize to  ─▶  gate → event core →   ─▶  embeddings  ─▶  corroborate ─▶  typed edges
 X (curated) ──┤   canonical IDs     entities+link →           + time window   numeric check   event→race links
 Race ratings ─┘   raw → S3/disk     classify → stance →       + entity        contradiction   salience feed
                   content-hashed    relationships             overlap         flags           rollup views
                                                               (LLM tiebreak)
                                                                     │
                                                         Postgres 16 + pgvector
                                                                     │
                             FastAPI query API  ◀────────────────────┘
                                     │
                             Next.js terminal UI
```

- **Push mode:** a scheduled pipeline builds a salience-ranked "what changed" feed. No LLM in the
  ranking: `salience = recency decay + log(source count) + entity importance + verification bonus +
  election proximity`, all in code.
- **Pull mode:** `RSCH <question>` retrieves events (pgvector + SQL), then the LLM synthesizes an
  answer over only the retrieved records, with citations and a confidence.

### Design rules

1. **Canonical IDs, never name strings.** Every entity resolves to a stable ID: bioguide for members
   of Congress, FEC candidate/committee ID, FRED series ID, state FIPS, and `STATE-OFFICE-CYCLE` for
   races (e.g. `AZ-SEN-2026`). Mentions that don't resolve go to a review queue.
2. **Provenance on every claim:** source URL, verbatim span, timestamp, and confidence. Claims without
   a span are rejected.
3. **The LLM is the structuring layer, not the source of truth.** It extracts, links, classifies, and
   synthesizes. It is not the database and it does not decide what is a fact.
4. **No LLM in deterministic ranking.** Clustering thresholds, evidence selection, and salience are
   code. The LLM only labels and breaks ties.
5. **Confidence per field.** Low-confidence extractions go to review.
6. **Correlation, never causation.** Edges say `CORRELATES_WITH`. There is no `CAUSES` edge.
7. **Evals gate prompt changes.** Every extraction prompt change is scored against a golden set.
8. **Idempotent ingestion.** Every raw item is content-hashed and never reprocessed.

## Data sources

| Source | Provides | Anchors to |
|---|---|---|
| Congress.gov API | bills, members, committees | bioguide |
| Voteview (UCLA) | Senate roll-call votes | bioguide |
| FRED | macro series (CPI, unemployment, rates…) | FRED series ID |
| BLS | release-time ground truth for numeric verification | — |
| FEC (api.data.gov) | candidates, committees, fundraising | FEC ID |
| X API | statements from a curated set of senators + media accounts | bioguide |
| Cook Political Report, Inside Elections | Senate race ratings + history | race ID |

Scrapers respect `robots.txt`. A rater whose robots file refuses us is skipped with a log line.

## The terminal

| Command | Shows |
|---|---|
| `FEED` | live "what changed" feed (default screen) |
| `EVT <id>` | full event object: sources, entities, stances, verification, related events |
| `RACE <code>` | race dossier, e.g. `RACE OH-SEN` |
| `ENT <name \| id>` | entity dossier, e.g. `ENT MURKOWSKI` |
| `STANCE <ent> <topic>` | position timeline, e.g. `STANCE MURKOWSKI INFLATION` |
| `RSCH <question>` | grounded answer over retrieved records, with citations |
| `HELP` | command reference |

Every rendered claim links to its provenance (source, span, confidence).

## Eval

The extraction DAG is scored against a hand-labeled golden set in
`pipeline/brokeberg/eval/golden/`. The baseline covers the 30 verified real items (X posts, bills,
Senate votes, FEC filings), with `claude-sonnet-4-6` and the cheap passes on `claude-haiku-4-5`
(prompt `day3-v2`):

| Pass | Metric | Score |
|---|---|---|
| Gate | accuracy | 0.93 |
| Event type | accuracy | 0.96 |
| Entities | precision / recall / F1 | 1.00 / 0.92 / 0.96 |
| Topics | precision / recall / F1 | 0.70 / 0.94 / 0.80 |
| Stance | precision / recall / F1 | 0.40 / 1.00 / 0.57 |
| Stance | direction accuracy | 1.00 |

These are small samples (25 gold entities, 17 gold topics), so one item moves a metric by several
points. Entity precision used to read 0.67 because the scorer counted each bill's sponsor as an
extra entity whenever the extractor also tagged them `actor`. Sponsors are structural and never
labeled, so the scorer now excludes them; the old baseline is kept as
`baseline.pre-structural-dedupe.json`. Topic and stance precision are the weak spots: the model
over-tags topics (e.g. reading "Dream Act" in a bill title as immigration, now a golden case) and
attaches stances the golden set doesn't label, with 0.00 position accuracy even though it gets the
direction right every time.

## Repo layout

```
pipeline/            Python 3.11 — the whole backend
  brokeberg/
    taxonomy.py      controlled vocabulary (single source of truth)
    ids/             canonical-ID resolvers (bioguide, FEC, FRED, FIPS, bills)
    ingest/          one connector per source behind a common interface
    extract/         extraction DAG passes (pydantic-validated JSON output)
    cluster/         embedding + entity clustering → materialized event objects
    verify/          corroboration, numeric checks vs FRED/BLS, contradiction flags
    graph/           typed edges, event→race linkage, salience, rollup views
    api/             FastAPI query API (feed, event, race, entity, stance, RSCH)
    llm/ embed/      provider interfaces: Anthropic | Bedrock, local bge | Titan v2
    aws/             Lambda handlers, Secrets Manager
    eval/            golden set, scorer, committed baseline
  tests/             pytest with recorded vcrpy cassettes (no live API calls)
web/                 Next.js (App Router) terminal UI, proxies /api/* to the Python API
infra/               AWS CDK (Python) stacks + ops scripts
tasks/               per-phase build briefs
```

## Running locally

**Prerequisites:** Docker, [uv](https://docs.astral.sh/uv/) (Python 3.11), Node 20+, and API keys
for Anthropic, Congress.gov, FRED, BLS, api.data.gov (FEC), and optionally X. See
[`SETUP.md`](SETUP.md) for the full walkthrough.

```bash
# 1. Secrets: create .env at the repo root (never committed)
#    ANTHROPIC_API_KEY, CONGRESS_API_KEY, FRED_API_KEY, BLS_API_KEY,
#    DATA_GOV_API_KEY, X_BEARER_TOKEN

# 2. Database
make up               # Postgres 16 + pgvector in Docker
make migrate          # alembic upgrade head
make seed             # reference data: senators, indicators, states, races

# 3. Pipeline
make ingest-once      # one ingestion cycle (REPLAY=1 replays archived raw items)
make extract          # LLM extraction DAG
make cluster          # cluster into event objects
make graph            # verify, build edges, salience

# 4. Serve
make api              # FastAPI on :8000
make web              # Next.js terminal on :3000
```

Development commands:

```bash
make test             # pytest, fully offline
make eval             # score extraction against the golden set
make lint             # ruff + mypy
```

Local dev embeds with `BAAI/bge-large-en-v1.5` via `sentence-transformers`. Prod uses Bedrock
Titan Text Embeddings v2. Both are 1024-dim, so the same `vector(1024)` column serves both.

## Deploying to AWS

Provider swaps are env-only (`LLM_PROVIDER=bedrock`, `EMBED_PROVIDER=bedrock`), with no code
changes. The stacks live in `infra/` and deploy to `us-east-2`:

| Stack | Contents |
|---|---|
| `BrokebergData` | S3 raw bucket (`{source}/{yyyy}/{mm}/{dd}/`), app-config secret in Secrets Manager |
| `BrokebergPipeline` | an EventBridge Scheduler rule + ingest Lambda per connector → SQS FIFO (with DLQ) → a process Lambda (extract → cluster → graph), with a daily extraction cap |
| `BrokebergApi` | the FastAPI app on Lambda (Mangum) behind a Function URL |

Aurora PostgreSQL Serverless v2 uses express configuration (IAM auth, 0–2 ACU, auto-pause).
CloudFormation can't create that, so `infra/scripts/express_db.py` manages the cluster outside CDK.
Lambdas connect with IAM tokens, so there is no database password to manage.

```bash
cd pipeline && uv run python ../infra/scripts/express_db.py create
cd ../infra
npx aws-cdk@2 deploy BrokebergData
uv run python scripts/push_secrets.py
npx aws-cdk@2 deploy BrokebergPipeline
npx aws-cdk@2 deploy BrokebergApi
```

The web UI deploys to Vercel with `API_URL` set to the API stack's Function URL.

To stop all schedules and Bedrock spend, destroy `BrokebergPipeline`.

## Further reading

- [`PLAN.md`](PLAN.md): the full rationale for each phase
- [`SETUP.md`](SETUP.md): one-time environment setup
- [`tasks/`](tasks/): per-phase build briefs

## License

[MIT](LICENSE)
