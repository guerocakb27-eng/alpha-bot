#!/usr/bin/env bash
# Alpha Bot — one-click local bootstrap.
# Creates the venv, installs Python deps, initializes the DB, builds the dashboard.
# Idempotent: safe to re-run.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

cyan()   { printf "\033[96m%s\033[0m\n" "$*"; }
green()  { printf "\033[92m%s\033[0m\n" "$*"; }
red()    { printf "\033[91m%s\033[0m\n" "$*"; }
yellow() { printf "\033[93m%s\033[0m\n" "$*"; }

# ─── Prerequisites ──────────────────────────────────────────────────
cyan "→ Checking prerequisites…"

if ! command -v python3 >/dev/null 2>&1; then
    red "python3 not found. Install Python 3.11+ first."; exit 1
fi
PY_VER=$(python3 -c 'import sys; print("{0}.{1}".format(*sys.version_info[:2]))')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    red "Python $PY_VER detected. Need 3.11 or newer."; exit 1
fi
green "  python $PY_VER ✓"

if ! command -v node >/dev/null 2>&1; then
    yellow "  node not found — dashboard build will be skipped"
    HAS_NODE=0
else
    NODE_MAJOR=$(node -v | sed 's/^v//' | cut -d. -f1)
    if [ "$NODE_MAJOR" -lt 18 ]; then
        yellow "  node $NODE_MAJOR detected (need 18+); dashboard build will be skipped"
        HAS_NODE=0
    else
        green "  node $(node -v) ✓"
        HAS_NODE=1
    fi
fi

# ─── .env ───────────────────────────────────────────────────────────
if [ ! -f .env ]; then
    cp .env.example .env
    yellow "→ Created .env from .env.example — fill in BINANCE_API_KEY / BINANCE_SECRET"
else
    green "→ .env already present"
fi

# ─── Python venv ────────────────────────────────────────────────────
if [ ! -d .venv ]; then
    cyan "→ Creating virtualenv (.venv)…"
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

cyan "→ Installing Python dependencies…"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
green "  ✓ deps installed"

# ─── DB init + seed ─────────────────────────────────────────────────
cyan "→ Initializing database + seeding defaults…"
python -c "from database.models import init_db; from database.seed import seed; init_db(); seed(); print('  ✓ DB ready')"

# ─── Dashboard build ────────────────────────────────────────────────
if [ "$HAS_NODE" = "1" ]; then
    cyan "→ Building dashboard (npm install + build)…"
    pushd dashboard >/dev/null
    npm install --no-audit --no-fund --silent
    npm run build --silent
    popd >/dev/null
    green "  ✓ dashboard built at dashboard/dist/"
fi

# ─── Next steps ─────────────────────────────────────────────────────
echo
green "════════════════ SETUP COMPLETE ════════════════"
echo
echo "Next steps:"
echo "  1. Fill in BINANCE_API_KEY / BINANCE_SECRET in $ROOT/.env"
echo "  2. Start the API:           source .venv/bin/activate && uvicorn api.main:app --port 8000"
echo "  3. (Optional) dev dashboard: cd dashboard && npm run dev"
echo "  4. Open http://localhost:5173 (dev) or http://localhost:8000/docs (API)"
echo
echo "Smoke tests:"
echo "  python scripts/test_phase1.py     # signal engine end-to-end"
echo "  python scripts/test_phase3.py     # sentiment engine"
echo "  python scripts/test_phase4.py     # paper-trade pipeline"
echo "  python scripts/test_phase5.py     # learning engine"
echo
echo "Docker alternative:"
echo "  docker compose up --build         # full stack incl. postgres + redis"
