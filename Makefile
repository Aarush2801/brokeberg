up:          ; docker compose up -d
migrate:     ; cd pipeline && uv run alembic upgrade head
seed:        ; cd pipeline && uv run python -m brokeberg.db.seed
fetch-senators: ; cd pipeline && uv run python -m brokeberg.db.fetch_senators
test:        ; cd pipeline && uv run pytest -q
eval:        ; cd pipeline && uv run python -m brokeberg.eval.run $(ARGS)
lint:        ; cd pipeline && uv run ruff check . && uv run mypy brokeberg
ingest-once: ; cd pipeline && uv run python -m brokeberg.ingest.run_once $(if $(REPLAY),--replay,)
extract:     ; cd pipeline && uv run python -m brokeberg.extract.run $(ARGS)
web:         ; cd web && npm run dev
