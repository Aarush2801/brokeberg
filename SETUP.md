# SETUP.md — Mac + VS Code + Claude Code

One-time setup for macOS, using the **Claude Code VS Code extension** (inline diffs) and **uv** (fast
Python). Do this once before Day 1. The account/key signups can be done during Claude Code cooldowns.
For the ultra-granular, click-by-click version see `SETUP_STEPS.md`.

---

## 1. Base tools (Homebrew)

```bash
# install Homebrew if you don't have it:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install git awscli uv
brew install --cask visual-studio-code docker
```
- Open **Docker Desktop** once and let it finish starting (steady whale icon = running).
- `uv` manages Python for us, so you don't need to `brew install python`.
- Install Python 3.11 via uv: `uv python install 3.11`.

Verify: `git --version && uv --version && code --version && docker --version && aws --version`.

If `code` isn't found: open VS Code → `Cmd+Shift+P` → "Shell Command: Install 'code' command in PATH".

---

## 2. Claude Code (needs Claude Pro) + VS Code extension

```bash
curl -fsSL https://claude.ai/install.sh | bash     # installs the CLI (no Node needed)
```
Then wire it into VS Code:
1. `cd` into your project folder (after Section 3) and run `code .` to open it in VS Code.
2. Open the integrated terminal: **Ctrl+`** (backtick).
3. Run `claude` in that terminal → **the VS Code extension auto-installs**. Choose **"Claude App
   (Pro/Max)"** and log in with your Pro account.
4. Toggle the Claude panel with **Cmd+Esc**; insert a file reference into a prompt with **Cmd+Option+K**.
5. Set the default model: `claude config set model sonnet`.

You now get agent edits as **reviewable inline diffs** in the editor. Use `/usage` to watch your Pro
session + weekly bars; `/clear` and `/compact` to keep context (and token burn) small.

**Recommended VS Code extensions** (Extensions panel, `Cmd+Shift+X`): Python (`ms-python.python`),
Pylance, **Ruff** (`charliermarsh.ruff`), Docker. Enable *Format on Save* with Ruff.

---

## 3. Accounts + API keys (all free unless noted)

Collect each into a scratch file, then move into `.env` (Section 6).

| # | Service | Where | Note |
|---|---|---|---|
| 1 | **Anthropic API key** (app's dev LLM, separate from Claude Code) | console.anthropic.com → API Keys | add $5–10 credit |
| 2 | Congress.gov | api.congress.gov/sign-up | emailed key |
| 3 | FRED | fred.stlouisfed.org → My Account → API Keys | — |
| 4 | BLS | data.bls.gov/registrationEngine | emailed key |
| 5 | FEC / api.data.gov | api.data.gov/signup | one key covers FEC |
| 6 | Census (optional) | api.census.gov/data/key_signup.html | FIPS |
| 7 | **X API** (pay-per-use) | developer.x.com | reads $0.005 each → ~$15–30/mo |
| 8 | **AWS** | aws.amazon.com | set a Budget alert immediately |
| 9 | GitHub | github.com | new private repo `brokeberg` |
| 10 | Vercel | vercel.com | connect repo on Day 6 |

NYT poll data + race-ratings sites need no key (scrape w/ attribution).

AWS one-time: create an IAM admin user, `aws configure` (region `us-east-1`), and in **Bedrock → Model
access** request **Anthropic Claude** + **Titan Text Embeddings V2** now (it has lead time).

---

## 4. Repo + scaffold

```bash
cd ~ && git clone <your repo URL> && cd brokeberg
# drop in: CLAUDE.md PLAN.md SETUP.md SETUP_STEPS.md RESOURCES.md tasks/
mkdir -p pipeline web infra
printf ".env\nkeys-scratch.txt\n__pycache__/\n*.pyc\n.venv/\nnode_modules/\n.vcr_cassettes/\n" > .gitignore
git add . && git commit -m "scaffold: docs + gitignore"
code .     # open in VS Code
```

---

## 5. Local database (Docker Postgres + pgvector)

```bash
cat > docker-compose.yml <<'EOF'
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: brokeberg
      POSTGRES_PASSWORD: brokeberg
      POSTGRES_DB: brokeberg
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
volumes: { pgdata: {} }
EOF

docker compose up -d
psql postgresql://brokeberg:brokeberg@localhost:5432/brokeberg -c "CREATE EXTENSION IF NOT EXISTS vector; SELECT 'ok';"
```

---

## 6. Environment file

```bash
cat > .env <<'EOF'
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=
LLM_MODEL=claude-sonnet-5-5
EMBED_PROVIDER=local
EMBED_MODEL=BAAI/bge-large-en-v1.5
EMBED_DIM=1024
DATABASE_URL=postgresql+psycopg://brokeberg:brokeberg@localhost:5432/brokeberg
CONGRESS_API_KEY=
FRED_API_KEY=
BLS_API_KEY=
DATA_GOV_API_KEY=
CENSUS_API_KEY=
X_BEARER_TOKEN=
AWS_REGION=us-east-1
S3_RAW_BUCKET=brokeberg-raw-yourname
EOF
```
Edit `.env` and paste each key. Confirm `git status` does **not** list `.env`.

---

## 7. Python environment (uv — no venv activation needed)

```bash
cd pipeline
uv init --python 3.11            # creates pyproject.toml + a managed .venv
uv add "sqlalchemy>=2" alembic "psycopg[binary]" pgvector "pydantic>=2" pydantic-settings \
       httpx tenacity python-dotenv vcrpy pytest ruff mypy anthropic boto3 \
       sentence-transformers feedparser selectolax beautifulsoup4 rapidfuzz
# pre-download the embedding model (~1.3 GB) so Day 4 is instant:
uv run python -c "from sentence_transformers import SentenceTransformer as M; M('BAAI/bge-large-en-v1.5')"
cd ..
```
With uv you run everything via `uv run <cmd>` — no `source .venv/bin/activate`.

---

## 8. Makefile (uv-native)

```bash
cat > Makefile <<'EOF'
up:          ; docker compose up -d
migrate:     ; cd pipeline && uv run alembic upgrade head
test:        ; cd pipeline && uv run pytest -q
eval:        ; cd pipeline && uv run python -m brokeberg.eval.run
lint:        ; cd pipeline && uv run ruff check . && uv run mypy brokeberg
ingest-once: ; cd pipeline && uv run python -m brokeberg.ingest.run_once
web:         ; cd web && npm run dev
EOF
```

---

## 9. Smoke test (ready when all pass)

```bash
docker compose up -d
psql "postgresql://brokeberg:brokeberg@localhost:5432/brokeberg" -c "SELECT 1;"
cd pipeline
uv run python -c "import os,dotenv; dotenv.load_dotenv('../.env'); print('key:', bool(os.getenv('ANTHROPIC_API_KEY')))"
uv run python -c "from sentence_transformers import SentenceTransformer as M; print('dim:', len(M('BAAI/bge-large-en-v1.5').encode('hi')))"
cd ..
```
Expect: `1`, `key: True`, `dim: 1024`.

---

## 10. First Claude Code session (in VS Code)

In VS Code's integrated terminal (`Ctrl+\``), run `claude`, then type:
> Read CLAUDE.md, then read tasks/day-0-setup.md and do it. Use plan mode first and show me the plan.

Review the plan → approve → review the inline diffs → commit. Each later session: update the **ACTIVE**
line in `CLAUDE.md`, then *"Read CLAUDE.md, then read tasks/day-N-….md and do it."*
