# Day 2 — Ingestion connectors

> Load: `CLAUDE.md`, this file. Good candidate for **subagents** — build connectors in parallel.
> Each connector is independent; a common interface keeps the rest of the system source-agnostic.

## Objective
One connector per source, each normalizing to canonical IDs and writing `raw_items`. A single
`ingest/run_once.py` runs them all. Tests use recorded fixtures, never live APIs.

## Common interface (`ingest/base.py`)
```python
class Connector(Protocol):
    source: str
    source_type: str          # from taxonomy
    def fetch(self, since: datetime) -> Iterable[RawRecord]: ...
# RawRecord -> {url, text, event_time, raw_payload}
```
Pipeline wrapper computes `content_hash`, dedups against `raw_items`, resolves obvious entities to
canonical IDs where cheap, and inserts. Use `tenacity` for retries + backoff on all HTTP.

## Connectors to build (`ingest/sources/`)
1. `congress.py` — bills, roll-call votes, member statements (Congress.gov API). Map members→bioguide.
2. `fred.py` — pull the ~20 seeded series → `indicators` rows (not raw_items; these are structured data).
3. `bls.py` — latest release values for the key series → `indicators` (verification reference).
4. `fec.py` — candidate + committee filings for the target races → `races.fec_candidate_ids`, finance meta.
5. `x.py` — recent posts from a curated account list (≤20, config file `ingest/x_accounts.yaml`).
   Use `/2/users/:id/tweets`; read-only; **log the per-pull read count** (cost visibility). ~100–200/day.
6. `nyt_polls.py` — fetch the NYT poll CSV(s) → `poll_averages` (attribution noted in code comment).
7. `ratings.py` — scrape topline race ratings from Cook/Sabato/Inside Elections → `race_ratings_history`.
   Respect robots.txt; cache aggressively; weekly cadence.

## Guardrails / tests
- `tests/test_ingest_*.py`: one recorded `vcrpy` cassette per connector; assert normalized output shape,
  canonical-ID mapping, and `content_hash` dedup (same item twice → one row).
- Secrets come from `config.Settings`, never hardcoded.
- Scrapers have a `robots_ok()` check and a per-domain rate limit.

## Definition of done
`make ingest-once` populates `raw_items`, `indicators`, `poll_averages`, `race_ratings_history` from
fixtures; `make test` green; the X connector prints its read count.

## Commit
`feat(ingest): connectors for congress, fred, bls, fec, x, nyt polls, race ratings`
