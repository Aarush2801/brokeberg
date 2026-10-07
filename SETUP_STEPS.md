# SETUP_STEPS.md — do-exactly-this (Mac + VS Code + Claude Code)

The granular companion to `SETUP.md`, for **macOS + VS Code + the Claude Code extension + uv**.
Every step is one action with a checkpoint. Do them **in order**; tick each box; fix any failed
checkpoint before moving on.

Legend: ⌨️ = type/paste a command, press Enter · ✅ = you should see this · ⚠️ = if it goes wrong.
"Terminal" = the macOS Terminal app for Sections 1–2; from Section 4 on, use **VS Code's integrated
terminal** (`Ctrl+\`` — the backtick key, top-left of the keyboard).

---

## Section 1 — Base tools

- [ ] Open **Terminal** (`Cmd+Space`, type `Terminal`, Enter).
- [ ] Install Homebrew — ⌨️:
  `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
  - [ ] ✅ "Installation successful!". ⚠️ If it prints a "Next steps" box with two `echo >> ~/.zprofile`
    lines, **copy-paste and run those two lines**, then quit and reopen Terminal.
- [ ] ⌨️ `brew --version` → ✅ `Homebrew 4.x`.
- [ ] ⌨️ `brew install git awscli uv`
- [ ] ⌨️ `brew install --cask visual-studio-code docker`
- [ ] Open **Docker Desktop** (`Cmd+Space` → "Docker"). Accept terms. Wait until the whale icon in the
  top menu bar stops animating. ✅ Steady icon = running.
- [ ] Install a managed Python — ⌨️ `uv python install 3.11` → ✅ "Installed Python 3.11.x".
- [ ] Verify — ⌨️ `git --version && uv --version && docker --version && aws --version`
  - [ ] ✅ four version lines, no "command not found".

---

## Section 2 — VS Code + the `code` command

- [ ] Open **VS Code** (`Cmd+Space` → "Visual Studio Code").
- [ ] Install the `code` shell command: `Cmd+Shift+P` → type `shell command` → click
  **"Shell Command: Install 'code' command in PATH"**.
- [ ] Back in Terminal — ⌨️ `code --version` → ✅ a version number. ⚠️ Not found → quit/reopen Terminal.
- [ ] Install extensions: in VS Code press `Cmd+Shift+X`, search and **Install** each:
  - [ ] **Python** (publisher Microsoft, id `ms-python.python`)
  - [ ] **Pylance**
  - [ ] **Ruff** (publisher Astral / `charliermarsh.ruff`)
  - [ ] **Docker** (Microsoft)
- [ ] (The **Claude Code** extension installs itself in Section 9 — don't install it manually yet.)

---

## Section 3 — Claude Code CLI

- [ ] In Terminal — ⌨️ `curl -fsSL https://claude.ai/install.sh | bash`
  - [ ] ✅ "Claude Code installed". ⚠️ `claude: command not found` after → quit and reopen Terminal.
- [ ] ⌨️ `claude --version` → ✅ a version number. (You'll log in from inside VS Code in Section 9.)
- [ ] ⌨️ `claude config set model sonnet` → ✅ "Set model to sonnet".

---

## Section 4 — Create accounts & collect API keys

Make a scratch file to hold keys as you get them — ⌨️ `echo "" > ~/keys-scratch.txt && open -e ~/keys-scratch.txt`.
Paste each key into it as `NAME=value`. (You'll move them to `.env` in Section 7; `keys-scratch.txt` is
git-ignored.)

### 4.1 Anthropic API key (app's dev LLM — separate from Claude Code)
- [ ] **console.anthropic.com** → log in → sidebar **API Keys** → **Create Key** → name `brokeberg-dev`
  → **Copy** (starts `sk-ant-`). ⚠️ Shown once — paste as `ANTHROPIC_API_KEY=...` now.
- [ ] Sidebar **Billing** → add $5–10 credit (a $0 balance makes dev extraction error out).

### 4.2 Congress.gov
- [ ] **api.congress.gov/sign-up** → name + email → submit → check email → paste `CONGRESS_API_KEY=...`.

### 4.3 FRED
- [ ] **fred.stlouisfed.org** → create account → verify email → top-right **My Account → API Keys →
  Request API Key** → paste `FRED_API_KEY=...`.

### 4.4 BLS
- [ ] **data.bls.gov/registrationEngine** → email + name → submit → confirm via email → paste `BLS_API_KEY=...`.

### 4.5 FEC (api.data.gov)
- [ ] **api.data.gov/signup** → name + email → submit → key in email → paste `DATA_GOV_API_KEY=...`.

### 4.6 Census (optional)
- [ ] **api.census.gov/data/key_signup.html** → submit → key emailed → paste `CENSUS_API_KEY=...`.

### 4.7 X API (pay-per-use)
- [ ] **developer.x.com** → sign in → create a **Project** + **App** (name `brokeberg`) → add a payment
  method → App → **Keys and tokens** → generate a **Bearer Token** → Copy → paste `X_BEARER_TOKEN=...`.
  - [ ] ⚠️ You're reading only; ignore write/post setup.

### 4.8 GitHub
- [ ] **github.com** → **New repository** → name `brokeberg` → **Private** → Create. Copy the **HTTPS**
  clone URL (green **Code** button).

### 4.9 AWS (account now; services on Day 7)
- [ ] **aws.amazon.com** → Create an AWS Account (email, card, phone).
- [ ] **Budget alert first:** console search "Budgets" → **Create budget** → Cost budget → Monthly →
  **$30** → email alert at **80%** → Create. ✅ Budget listed.
- [ ] IAM user: search "IAM" → **Users → Create user** `brokeberg-dev` → attach **AdministratorAccess** →
  Create → open user → **Security credentials → Create access key → CLI** → copy Access key + Secret.
- [ ] In Terminal — ⌨️ `aws configure` → paste key, secret, region `us-east-1`, output `json`.
  - [ ] ✅ ⌨️ `aws sts get-caller-identity` prints your account.
- [ ] **Bedrock access (lead time — do now):** search "Bedrock" → **Model access → Manage/Enable** →
  tick **Anthropic Claude** + **Titan Text Embeddings V2** → submit. ✅ Status → "Access granted" (may lag).

### 4.10 Vercel
- [ ] **vercel.com** → Sign up → "Continue with GitHub" → authorize. (Connect repo on Day 6.)

- [ ] **Checkpoint:** `keys-scratch.txt` has 7 keys (ANTHROPIC, CONGRESS, FRED, BLS, DATA_GOV, X_BEARER,
  + optional CENSUS), AWS is configured, Bedrock access requested. Fix any gap before continuing.

---

## Section 5 — Get the repo + open in VS Code

- [ ] ⌨️ `cd ~ && git clone <your HTTPS repo URL> && cd brokeberg`
- [ ] Copy the generated files in so you have:
  `CLAUDE.md PLAN.md SETUP.md SETUP_STEPS.md RESOURCES.md tasks/day-0..7.md`
  - [ ] ⌨️ `ls && ls tasks` → ✅ all present.
- [ ] ⌨️ `mkdir -p pipeline web infra`
- [ ] ⌨️ `printf ".env\nkeys-scratch.txt\n__pycache__/\n*.pyc\n.venv/\nnode_modules/\n.vcr_cassettes/\n" > .gitignore`
- [ ] ⌨️ `git add . && git commit -m "scaffold: docs + gitignore"`
- [ ] ⌨️ `code .` → ✅ VS Code opens on the `brokeberg` folder. **From here, use VS Code's integrated
  terminal** (`Ctrl+\``) for all commands.

---

## Section 6 — Local database (Docker Postgres + pgvector)

- [ ] Confirm Docker Desktop is running (steady whale icon).
- [ ] In VS Code's terminal, ⌨️ paste the whole block:
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
```
- [ ] ⌨️ `docker compose up -d` → ✅ "Started". ⚠️ "port 5432 already in use" → stop the other Postgres
  or change the left `5432` to `5433` (and update the URL in Section 7).
- [ ] ⌨️ `docker compose exec db psql -U brokeberg -c "CREATE EXTENSION IF NOT EXISTS vector; SELECT 'ok';"`
  - [ ] ✅ prints `ok`.

---

## Section 7 — Environment file

- [ ] ⌨️ paste this block:
```bash
cat > .env <<'EOF'
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=
LLM_MODEL=claude-sonnet-4-6
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
- [ ] Open `.env` in VS Code (click it in the Explorer), paste each key from `keys-scratch.txt`, **Save**
  (`Cmd+S`). ✅ No blank `=` except CENSUS (optional).
- [ ] ⌨️ `git status` → ✅ `.env` is **not** listed (it's ignored).

---

## Section 8 — Python environment (uv)

- [ ] ⌨️ `cd pipeline`
- [ ] ⌨️ `uv init --python 3.11` → ✅ creates `pyproject.toml` (and a sample `main.py` — Day 0 cleans it up).
- [ ] ⌨️ paste:
  `uv add "sqlalchemy>=2" alembic "psycopg[binary]" pgvector "pydantic>=2" pydantic-settings httpx tenacity python-dotenv vcrpy pytest ruff mypy anthropic boto3 sentence-transformers feedparser selectolax beautifulsoup4 rapidfuzz`
  - [ ] ✅ "Resolved … packages" + a `.venv` and `uv.lock` appear. ⚠️ A `psycopg` build error is rare on
    Mac with uv's wheels; if it happens, ⌨️ `brew install libpq` and retry.
- [ ] Pre-download the embedding model — ⌨️:
  `uv run python -c "from sentence_transformers import SentenceTransformer as M; M('BAAI/bge-large-en-v1.5')"`
  - [ ] ✅ Downloads ~1.3 GB then exits silently. (One-time.)
- [ ] ⌨️ `cd ..`
- [ ] Point VS Code at this interpreter: `Cmd+Shift+P` → "Python: Select Interpreter" → pick the one under
  `pipeline/.venv`. ✅ Bottom bar shows the venv Python.

---

## Section 9 — Claude Code in VS Code (log in + extension)

- [ ] In VS Code's integrated terminal (`Ctrl+\``), ⌨️ `claude`.
  - [ ] ✅ VS Code prompts to install the **Claude Code extension** → Install → **reload** if asked.
  - [ ] Choose **"Claude App (Pro/Max)"** → a browser opens → log in with **Claude Pro** → Authorize.
- [ ] ✅ Press **Cmd+Esc** → the Claude panel toggles. ⌨️ in it `/usage` → ✅ session + weekly bars show.
- [ ] You now review agent edits as **inline diffs** in the editor. Good — that's the point of VS Code here.

---

## Section 10 — Makefile + smoke test

- [ ] ⌨️ paste (from repo root):
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
- [ ] ⌨️ `docker compose up -d`
- [ ] ⌨️ `docker compose exec db psql -U brokeberg -c "SELECT 1;"` → ✅ `1`.
- [ ] ⌨️ `cd pipeline`
- [ ] ⌨️ `uv run python -c "import os,dotenv; dotenv.load_dotenv('../.env'); print('key:', bool(os.getenv('ANTHROPIC_API_KEY')))"`
  → ✅ `key: True`.
- [ ] ⌨️ `uv run python -c "from sentence_transformers import SentenceTransformer as M; print('dim:', len(M('BAAI/bge-large-en-v1.5').encode('hi')))"`
  → ✅ `dim: 1024`.
- [ ] ⌨️ `cd ..`

---

## Section 11 — First Claude Code session

- [ ] In the Claude panel (**Cmd+Esc**) or the terminal `claude`, type exactly:
  `Read CLAUDE.md, then read tasks/day-0-setup.md and do it. Use plan mode first and show me the plan before writing files.`
- [ ] Review the plan → approve → watch it build → **review the inline diffs** → when green, in the
  terminal ⌨️:
  `git add . && git commit -m "chore: python skeleton — config, db session, llm+embed interfaces, taxonomy, alembic"`
- [ ] Before each future session: edit the **ACTIVE** line at the bottom of `CLAUDE.md`, then tell Claude:
  *"Read CLAUDE.md, then read tasks/day-N-….md and do it."*

---

## Daily reset ritual
1. Open VS Code on `brokeberg/` → `make up` (start DB).
2. One task per session. `/clear` between unrelated tasks; `/compact` when context grows.
3. `/usage` to watch your Pro bars; stop before the session cap, switch to reading/manual work in cooldown.
4. End each phase: `make test` (and `make eval` from Day 3) → review diffs → commit with the day file's message.
