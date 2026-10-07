# Day 7 — Deploy, eval & ship

> Load: `CLAUDE.md`, this file. Keep it light — this is buffer. If earlier phases overran, deploy a
> subset and document the rest. Switch providers via env, not code changes.

## Objective
Run the pipeline on AWS (the cloud/data-engineering story), confirm the eval numbers, ship the web UI,
and write the README + résumé bullet.

## Build (`infra/` — AWS CDK in Python)

### 1. Minimal real footprint
- **S3** raw bucket (`S3_RAW_BUCKET`), partitioned `s3://.../{source}/{yyyy}/{mm}/{dd}/`.
- **Aurora PostgreSQL Serverless v2** + pgvector; run Alembic migrations against it. (Set a low max ACU
  and a budget alert — you already created the alert in SETUP.)
- **EventBridge Scheduler** rules per source (FRED daily, Congress/FEC hourly, X every 15–30 min, ratings
  weekly) → **Lambda** per connector.
- **Lambda** for the extraction/cluster/verify run, triggered off new raw items (SQS between ingest and
  processing, with a DLQ).
- **Bedrock**: flip `LLM_PROVIDER=bedrock` and `EMBED_PROVIDER=bedrock` (Titan v2); confirm model access
  was granted (requested in SETUP). Same interfaces, no code change.
- **CloudWatch**: structured logs from every stage = observability.

### 2. Web
- Deploy `web/` to **Vercel** (connect the GitHub repo). Point it at the API (API Gateway + Lambda, or
  the FastAPI on a small Fargate task). Set env for the prod DB.

## Eval & docs
- Run `make eval` against the deployed pipeline's output; record per-pass precision/recall in the README.
- `README.md`: one-paragraph thesis, architecture diagram (reuse your own), data sources, the golden rules,
  how to run locally, and the eval numbers.
- **Résumé bullet** (write it, keep it honest to what shipped), e.g.:
  *"Built a cloud-based political-economic intelligence platform (Python/AWS) that ingests Congress, FRED,
  FEC, X and polling data, uses an LLM extraction pipeline with canonical-ID entity resolution and a
  golden-set eval harness to build a provenance-tracked knowledge graph, and serves a terminal UI linking
  economic indicators to politicians and Senate races."*

## Guardrails
- Secrets via AWS Secrets Manager, not env files, in prod.
- One end-to-end check in the cloud: a scheduled pull → extracted event visible in the deployed UI.
- Budget alert confirmed active.

## Definition of done
Pipeline runs on a schedule in AWS; UI live on Vercel showing real data; README + eval numbers + résumé
bullet committed.

## Commit
`feat(infra): AWS deploy (EventBridge/Lambda/S3/Aurora/Bedrock) + Vercel; docs + eval`
