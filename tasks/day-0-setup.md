# Day 0 — Scaffold & config

> Load: `CLAUDE.md`, this file. Set `CLAUDE.md` ACTIVE = this file.
> Mostly non-agent work (SETUP.md); this session just wires the Python project skeleton.

## Objective
A runnable, tested Python project skeleton with config, DB session, LLM + embedding interfaces behind
env switches, and an empty Alembic migration chain. No business logic yet.

## Preconditions
SETUP.md steps 0–8 done: Docker DB up, `.env` filled, venv created, smoke test passes.

## Deliverables
1. `pipeline/pyproject.toml` (project metadata + deps + ruff/mypy/pytest config).
2. `pipeline/brokeberg/config.py` — pydantic-settings `Settings` loading `.env`; exposes DB URL, LLM
   provider/model, embed provider/model/dim, all source keys. Fail loudly if a required key is missing
   only when the component that needs it is used (lazy), not at import.
3. `pipeline/brokeberg/db/session.py` — SQLAlchemy 2.0 engine + session factory; pgvector registered.
4. `pipeline/brokeberg/llm/__init__.py` — `complete(prompt, *, schema=None) -> str|dict`. Routes
   `anthropic` (dev) vs `bedrock` (prod) by `LLM_PROVIDER`. When `schema` (a pydantic model) is passed,
   force JSON output and parse/validate into it; raise on invalid.
5. `pipeline/brokeberg/embed/__init__.py` — `embed(texts: list[str]) -> list[list[float]]`. Routes
   `local` (sentence-transformers bge-large) vs `bedrock` (Titan v2). Always returns `EMBED_DIM` vectors.
6. `pipeline/brokeberg/taxonomy.py` — all enums from CLAUDE.md as `StrEnum`s. This is the single source
   of truth; nothing hardcodes these strings elsewhere.
7. Alembic initialized (`alembic init`), configured to read `DATABASE_URL` from settings; one empty
   baseline revision.
8. `tests/test_smoke.py` — imports every module, asserts `embed(["x"])` returns dim == EMBED_DIM, asserts
   taxonomy enums are non-empty.

## Guardrails / tests
- `make lint` and `make test` both pass.
- No live API calls in tests (embedding runs locally; LLM is not called in smoke tests).

## Definition of done
`make up && make migrate && make test && make lint` all green from a clean checkout.

## Commit
`chore: python skeleton — config, db session, llm+embed interfaces, taxonomy, alembic`
