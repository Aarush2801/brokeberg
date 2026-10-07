# Day 6 — Terminal UI (wire to real data)

> Load: `CLAUDE.md`, this file. The look already exists (the mockup). This is data-plumbing, not new UI.
> Drop the existing mockup HTML into `web/` first as the starting point.

## Objective
Replace the mockup's hardcoded mock objects with live queries against the graph, behind a thin query API.
Keep the aesthetic and the six primitives exactly as they are.

## Build

### 1. Query API (`web/app/api/` route handlers, or a small FastAPI in `pipeline/api/`)
Endpoints, each calling the Day-5 views:
- `GET /api/feed` → salience feed
- `GET /api/event/:id` → event object
- `GET /api/race/:id` → race dossier
- `GET /api/entity/:id` → entity dossier
- `GET /api/stance?entity=&topic=` → stance timeline
- `GET /api/indicators` → ticker series (latest values + delta)
- `POST /api/query` → single-pass grounded RAG: retrieve from pgvector + SQL, `llm.complete` synthesizes
  over retrieved records, returns answer **with inline citations + confidence**. (The `RSCH` command.)

Every response carries provenance (source + span) and confidence — the UI already renders these.

### 2. Frontend (`web/`)
- Port the mockup into the Next.js App Router (one page, client component for the terminal).
- Command parser → fetch the matching endpoint → render with the existing primitives
  (command bar, feed row, KV block, table, timeline overlay, provenance popover).
- `FEED` loads on boot (push). All other commands are fetches (pull). Loading + empty + error states
  written as directions, not mood ("No events match — widen the window." not "Nothing here 🙁").
- Remove the "SAMPLE DATA" badge once real data flows.

## Guardrails / tests
- API contract tests: each endpoint returns the documented shape with provenance present.
- `POST /api/query` refuses to answer beyond retrieved records (no free-form generation); assert the
  answer's claims map to returned source IDs.
- Keyboard nav + focus-visible preserved; works down to mobile width.

## Definition of done
`make web` serves the terminal; `FEED`, `EVT`, `RACE`, `ENT`, `STANCE`, and one `RSCH` query all return
live, sourced data from the local graph.

## Commit
`feat(web): query API + terminal UI wired to the live graph`
