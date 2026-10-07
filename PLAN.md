# PLAN.md — Brokeberg, fully explained

This is the "why" behind every phase. `CLAUDE.md` is the terse spec the agent reads each session;
this document is the narrative you read once to hold the whole thing in your head. Each `tasks/day-N.md`
is the actionable brief for one work session.

---

## 1. The thesis (read this before anything)

Google answers *questions you already know to ask*. Brokeberg surfaces *what changed and what's
connected to it*. That difference is the entire reason to build it, and it shapes every design choice.

Two consequences:

- **The product is the structured dataset, not the UI or the chatbot.** The terminal is a thin window.
  The LLM at query time is a thin synthesis layer. The asset is the continuously-updated, entity-linked,
  provenance-carrying graph underneath. If you swap the UI or the model, the asset remains; if you drop
  the graph, you're back to a chatbot that guesses. Protect the graph's integrity above all.
- **There are two interaction modes.** *Push*: the "what changed" feed runs on a schedule whether or
  not anyone asks anything — no LLM involved, pure pipeline output. *Pull*: you ask a question and an
  LLM answers by retrieving from the pre-built graph and citing stored records. The MVP delivers push
  plus a single-pass pull. The looping deep-research agent is v2.

Why this beats "LLM + live web search": that approach does all the work *at query time* — slow,
uncached, un-aggregated, no memory across questions, no cross-source reconciliation. Brokeberg does the
structuring and aggregation *once, ahead of time*, and stores it. The query becomes cheap retrieval.

---

## 2. What makes or breaks it

Not the AWS boxes, not the UI. Two things:

1. **Extraction quality.** Turning messy text into correct, linked, structured records is the hard 20%
   that most of the effort goes into. Naive LLM prompting gives hallucinated stances, inconsistent entity
   names, and bad clusters. For a *political* tool, confidently wrong is worse than empty. The defenses
   are baked into the golden rules: canonical IDs, span-grounding, per-field confidence, and evals.
2. **Entity resolution.** "Senator Reyes," "Sen. K. Reyes," and "@KReyes" must all collapse to one node.
   We make most of this problem disappear by building the graph on **stable external IDs** (bioguide,
   FEC, FRED, FIPS) instead of LLM-extracted name strings. The LLM's job is *linking a mention to an
   existing ID*, not inventing an entity. Unresolved mentions go to a review queue, never silently in.

Everything else (ingest, store, serve) is commodity engineering. Spend your care on these two.

---

## 3. The data sources and why each

All free unless noted. Chosen for high signal and low noise; social is one input, never the backbone.

| Source | Gives us | Canonical ID it anchors |
|---|---|---|
| Congress.gov API | bills, votes, members, committees | bioguide |
| FRED | macro series (CPI, unemployment, rates…) | FRED series ID |
| BLS | release-time ground truth for prices/jobs | — (verification reference) |
| FEC (api.data.gov) | candidates, committees, fundraising | FEC candidate/committee ID |
| X API (pay-per-use, ~$15–30/mo at 100–200 reads/day) | real-time politician statements, salience | — (links to bioguide) |
| NYT poll database (no key, attribution) | poll averages (picked up from the shuttered 538) | — |
| Cook / Sabato / Inside Elections (scrape topline) | race ratings + rating history | race composite ID |
| Census (optional) | FIPS / geography | state FIPS |

X is cheap at this volume because you're *reading* posts ($0.005 each), not creating them; the famous
$0.20 URL surcharge is a write-side charge and does not apply. Curate hard (≤15–20 accounts) so the
noise stays manageable.

---

## 4. The pipeline, stage by stage (what each phase builds)

### Phase 1 — Schema + canonical IDs (Day 1)
The foundation. If the schema and ID model are wrong, every later phase inherits the error. We create
the DB spine and the resolvers that turn a mention or code into a canonical ID. **Why first:** the graph
is built on IDs, so the IDs must exist before anything writes to the graph.

### Phase 2 — Ingestion connectors (Day 2)
One connector per source behind a common interface. Each fetches, normalizes to canonical IDs, writes
the raw payload to storage (immutable audit log + replay) and the normalized record to Postgres.
**Why a common interface:** so the extraction pipeline downstream doesn't care where an item came from,
and so adding a source later is a drop-in. **Why recorded fixtures in tests:** so you can run the test
suite 50 times a day without hammering (or paying for) live APIs.

### Phase 3 — Extraction DAG (Day 3)
The heart. Each incoming item runs a multi-pass pipeline, not one mega-prompt:
`gate → event core → entity extract+link → classify → stance`. Each pass is a separate function with a
strict pydantic output schema, so you can (a) use a cheap model where possible, (b) debug which pass
failed, and (c) **measure precision/recall per pass**. We build the eval harness and a 30–50 item golden
set *today*, not at the end, because from here on every prompt change is measured, not vibed.

### Phase 4 — Clustering + the event object (Day 4)
Many raw items about one happening (a tweet, an article, a press release, a vote) must collapse into one
event. We cluster with embeddings + a time window + shared-entity overlap, using the LLM only to break
ties and write the human-readable title. The materialized **event object** is the core product
primitive — the "intelligence object" the terminal renders.

### Phase 5 — Verification + graph + elections (Day 5)
Selection is not verification. Here we actually check claims: cross-source corroboration (≥2 independent
sources → `corroborated`; one → `single_source`), numeric claims checked against FRED/BLS ground truth,
and contradiction flags against prior extractions. Then we materialize the typed **edges** that make the
graph a graph, and the **event→race linkage** that makes elections first-class (an event affects a race
when topic × jurisdiction × competitiveness line up, with a stored rationale and confidence).

### Phase 6 — The terminal UI (Day 6)
The look already exists (the mockup). This phase replaces mock data with real queries: a thin query API
and the six UI primitives (command bar, feed row, KV block, table, timeline overlay, provenance popover)
pointed at the live graph. Push mode = the feed; pull mode = typed commands that retrieve and render.

### Phase 7 — Deploy + eval + ship (Day 7)
Port ingestion to EventBridge + Lambda, extraction to Bedrock, DB to Aurora + pgvector; wire the salience
digest to a schedule; run the full eval and record P/R; deploy the web UI to Vercel; write the README and
the résumé bullet. Kept light on purpose — it's buffer, because something earlier will overrun.

---

## 5. Timelines and aggregation (the two concepts that tie it together)

**Timelines.** Everything is timestamped twice: `event_time` (when it happened) and `ingest_time` (when
we saw it). A timeline is just events for one node ordered by `event_time`. The powerful view overlays a
structured series (e.g., CPI from FRED) with the discrete events touching it on the same axis — that's the
"tariff announcement → import prices → inflation" picture.

**Aggregation happens at three levels, each a distinct mechanism:**
1. *Source → Event* (clustering, Phase 4): N raw items become one event.
2. *Event → Node views* (rollup, Phase 5): the edges let you aggregate every event touching an entity,
   race, or topic → the dossier pages.
3. *Events → Digest* ("what changed", Phase 6): a scheduled job ranks events by salience and emits the feed:
   `salience = w1·recency_decay + w2·log(1+source_count) + w3·entity_importance + w4·verification_bonus
   + w5·election_proximity`. Weights are tunable, and later *learned* from your daily hand-labeled list.

---

## 6. AWS, honestly

You asked for AWS and the event-driven shape genuinely fits: scheduled triggers, retries/DLQ, parallel
ingestion, managed model calls. But at MVP volume you don't *need* it to function — so we **develop
entirely locally** (Docker Postgres, Anthropic API) and treat AWS as the deployment target on Day 7:
`EventBridge → Lambda → S3 → SQS → Aurora+pgvector → Bedrock → API Gateway → Vercel`, with CloudWatch as
observability and Step Functions orchestrating the extraction DAG. This keeps the week productive instead
of fighting IAM on Day 1, while still giving you the real cloud/data-engineering story at the end.

---

## 7. How this maps to your calendar (Claude Pro)

Pro paces you with a rolling 5-hour session window (~10–40 Claude Code prompts) plus a weekly cap
(~40–80 Sonnet hours). The **session window is what binds you**, not the weekly cap. Expect ~4 substantial
tasks per day across ~2 windows, so each phase below takes ~1.5–2 Pro calendar days → **~12–14 days total**.
The eight `tasks/day-N.md` files are the *phases*; on Pro, most phases span two sittings. Do the
non-agent work (reading, keys, manual tweaks, diff review) during the cooldowns between windows.

Phase → Pro-day mapping:
- Day 0 setup → ½ day (mostly non-agent)
- Day 1 schema → Pro days 1–2
- Day 2 ingestion → Pro days 3–4
- Day 3 extraction → Pro days 5–6
- Day 4 clustering → Pro day 7
- Day 5 verify+graph → Pro days 8–9
- Day 6 UI → Pro day 10
- Day 7 deploy → Pro days 11–12 (+ day 13 buffer)

---

## 8. Definition of done (MVP)

- Ingestion pulls all sources on a schedule and normalizes to canonical IDs.
- Incoming items are extracted, linked, clustered into event objects, and verified, with provenance and
  confidence on every claim.
- The graph answers: a salience feed, an event object, a race dossier, an entity dossier, a stance timeline.
- One single-pass grounded query works end to end (retrieve → synthesize → cite).
- The eval harness reports extraction precision/recall against the golden set.
- It runs on AWS, and the web UI is live on Vercel.
- README explains the architecture; one résumé bullet captures it.

If you have to cut, cut in this order: the deep-research loop (already v2), the graph-explorer view, the
RAG query, the entity timeline. **Never cut:** canonical IDs, provenance, the eval harness.
