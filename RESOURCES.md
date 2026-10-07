# RESOURCES.md — what to learn, mapped to this project

Organized by the component it supports, with the phase you'll need it for. You don't need to master any
of these — read enough to not be flying blind when Claude Code writes that part, so you can review its
output critically. **URLs are canonical roots; if one drifted, the title still finds it.**

## Suggested order
Before Day 1: Python tooling + Postgres/pgvector basics.
Before Day 3: LLM structured extraction + evals (most important block).
Before Day 4: embeddings + vector search.
Before Day 5: entity resolution + knowledge-graph modeling.
Before Day 6: Next.js basics + RAG.
Before Day 7: event-driven AWS + Bedrock.
Anytime / deeper: DDIA, agents.

---

## 0. Claude Code (the tool you're driving)
*Needed: every day.*
- **Official docs** — https://docs.claude.com/en/docs/claude-code (read Overview, Common Workflows, and the CLAUDE.md / memory page).
- **"Claude Code best practices"** — Anthropic engineering blog (anthropic.com/engineering). The single highest-ROI read; covers CLAUDE.md, plan mode, context hygiene.
- Learn the commands: `/plan`, `/clear`, `/compact`, `/usage`. Watch your session bar.

## 1. Python project tooling
*Needed: Day 0–1.*
- **SQLAlchemy 2.0** — https://docs.sqlalchemy.org (do the "2.0 ORM Quickstart" + the Core tutorial).
- **Alembic (migrations)** — https://alembic.sqlalchemy.org (the tutorial; understand `revision` + `upgrade/downgrade`).
- **Pydantic v2** — https://docs.pydantic.dev (models + validation; this is how we force structured LLM output).
- **pytest** — https://docs.pytest.org ; **vcrpy** — github.com/kevin1024/vcrpy (recording HTTP so tests don't hit live APIs).
- **httpx** — https://www.python-httpx.org ; **tenacity** (retries) — tenacity.readthedocs.io.

## 2. Postgres + pgvector + vector search
*Needed: Day 1 (schema), Day 4 (clustering).*
- **PostgreSQL docs** — https://www.postgresql.org/docs (indexes, JSONB, arrays, materialized views — all used in the spine).
- **pgvector README** — https://github.com/pgvector/pgvector (THE resource: `vector` type, `ivfflat` vs `hnsw`, cosine distance, index tuning).
- Concept: "Postgres is enough" / "do you need a vector DB?" blog posts — understand why we're not adding a separate vector store.

## 3. Embeddings & semantic similarity
*Needed: Day 4.*
- **Vicki Boykis, "What are embeddings"** — vickiboykis.com/what_are_embeddings (free, excellent, from scratch).
- **sentence-transformers docs** — https://www.sbert.net (how `bge-large` turns text into vectors).
- **BGE model card** — huggingface.co/BAAI/bge-large-en-v1.5 (the exact model we use; note the 1024 dims + query instruction prefix).
- Concept: cosine similarity, nearest-neighbor search, why a time window + entity overlap beats pure similarity for clustering.

## 4. LLM structured extraction (the heart — spend the most time here)
*Needed: Day 3.*
- **Anthropic — Tool use / structured outputs** — https://docs.claude.com/en/docs/build-with-claude (forcing strict JSON is the backbone of every extraction pass).
- **Anthropic — Prompt engineering guide** — same docs site (clear instructions, examples, XML tags, chain-of-thought).
- **`instructor` library** — https://python.useinstructor.com (pydantic-validated LLM outputs; even if you don't use it, read how it thinks about structured extraction).
- Concept to internalize: span-grounding (make the model quote its source), per-field confidence, why many small passes beat one mega-prompt.

## 5. LLM evaluation
*Needed: Day 3 (build the harness) — do not skip.*
- **Hamel Husain, "Your AI product needs evals"** — hamel.dev/blog/posts/evals (the canonical practitioner piece; golden sets, why vibes-based prompting fails).
- **Hamel Husain, "LLM-as-a-judge"** posts — same blog.
- Concept: precision/recall per task, held-out golden set vs auto-growing set, measuring before/after a prompt change.

## 6. Entity resolution / record linkage
*Needed: Day 1 (resolvers), Day 3 (linking).*
- **Peter Christen, _Data Matching_** (Springer, 2012) — the canonical textbook; skim chapters on blocking + comparison + classification.
- **Splink docs** — moj-analytical-services.github.io/splink (modern, practical probabilistic linkage; good mental model even though we lean on canonical IDs).
- Concept: why anchoring on stable external IDs (bioguide/FEC/FRED/FIPS) makes most of this problem disappear.

## 7. Knowledge graphs (in a relational DB)
*Needed: Day 5.*
- **O'Reilly, _Graph Databases_** (Robinson, Webber, Eifrem — free PDF) — for graph *concepts* (nodes, typed edges, traversal). We implement these in Postgres, not Neo4j.
- Concept: adjacency via an `edges` table, one-hop neighborhood queries, why we avoid `CAUSES` edges.

## 8. RAG (retrieval-augmented generation)
*Needed: Day 6 (the query/`RSCH` path).*
- **Anthropic, "Contextual Retrieval"** — anthropic.com/news/contextual-retrieval (how to retrieve well; directly relevant to the query path).
- **LlamaIndex** or **LangChain** docs — conceptually (chunking, retrieval, grounding). You won't need the frameworks, but read the patterns.
- Concept: retrieve-then-synthesize, grounding the answer in retrieved records, never free-generating facts.

## 9. Event-driven architecture + AWS
*Needed: Day 7.*
- **AWS Well-Architected — Serverless Lens** — docs.aws.amazon.com (the mental model).
- **Serverless Land** — https://serverlessland.com (copy-paste EventBridge→Lambda→SQS patterns).
- Service docs: **Lambda**, **EventBridge**, **S3**, **SQS**, **Step Functions**, **Aurora Serverless v2**, **Amazon Bedrock** (model access + InvokeModel), all at docs.aws.amazon.com.
- **CDK Workshop** — https://cdkworkshop.com (the Python track; infra-as-code the way infra/ uses it).

## 10. Next.js / frontend
*Needed: Day 6.*
- **Next.js Learn** — https://nextjs.org/learn (official interactive course; App Router, route handlers for the API).
- You already have the terminal UI built, so focus on: App Router structure, `app/api/` route handlers, client components, and `fetch` from the client.

## 11. The domain (politics + economics data)
*Needed: Day 2 (shapes your connectors), ongoing.*
- **FRED API docs** — https://fred.stlouisfed.org/docs/api/fred (series, observations, release calendar).
- **Congress.gov API** — https://github.com/LibraryOfCongress/api.congress.gov (members, bills, votes; bioguide IDs).
- **FEC OpenFEC API** — https://api.open.fec.gov/developers (candidates, committees, filings; FEC IDs).
- **BLS Handbook of Methods — CPI** — bls.gov/opub/hom/cpi (understand what CPI/PCE/core actually measure, and when they release).
- **MIT Election Data + Science Lab** — https://electionlab.mit.edu (how election data is structured; good academic grounding).

## 12. Agents (for the v2 deep-research loop)
*Needed: after MVP.*
- **Anthropic, "Building effective agents"** — anthropic.com/engineering/building-effective-agents (plan–execute–reflect, when to loop, deterministic vs LLM steps). Directly informs your deep-research architecture.

## 13. Foundations (optional, deeper)
*Anytime — makes everything above click.*
- **Martin Kleppmann, _Designing Data-Intensive Applications_** — the systems bible: storage, indexing, batch vs stream, consistency. Overkill for the MVP, invaluable for the engineer you're trying to become.
