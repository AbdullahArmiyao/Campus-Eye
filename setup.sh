#!/usr/bin/env bash
# =============================================================================
# Campus Eye — Setup Script
# Run once after cloning to prepare the development environment.
# Usage: bash setup.sh [--gpu]
# =============================================================================
set -e

GPU_MODE=false
for arg in "$@"; do
  case $arg in
    --gpu) GPU_MODE=true ;;
  esac
done

echo "╔══════════════════════════════════════════╗"
echo "║        Campus Eye — Setup Script         ║"
echo "╚══════════════════════════════════════════╝"

# ── 1. Python version check ───────────────────────────────────────────────────
PYTHON=$(command -v python3.10 || command -v python3)
PY_VER=$($PYTHON --version 2>&1)
echo "▸ Using Python: $PY_VER ($PYTHON)"

MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")
if [ "$MAJOR" -lt 3 ] || [ "$MINOR" -lt 10 ]; then
  echo "✗ Python 3.10+ required. Install it and re-run."
  exit 1
fi
if [ "$MINOR" -ge 12 ]; then
  echo "  ℹ Python 3.12 detected — using compatible package versions."
fi

# ── 2. Virtual environment ────────────────────────────────────────────────────
if [ ! -d "venv" ]; then
  echo "▸ Creating virtual environment..."
  $PYTHON -m venv venv
fi
source venv/bin/activate
echo "▸ Activated venv: $(which python)"

# ── 3. Install dependencies ───────────────────────────────────────────────────
echo "▸ Installing Python dependencies (this may take several minutes)..."
pip install --upgrade pip

if [ "$GPU_MODE" = true ]; then
  echo "▸ GPU mode: installing onnxruntime-gpu..."
  # Add onnxruntime-gpu and skip CPU version
  grep -v '^onnxruntime$' requirements.txt > /tmp/req_gpu.txt
  echo 'onnxruntime-gpu' >> /tmp/req_gpu.txt
  pip install --no-cache-dir --timeout 120 -r /tmp/req_gpu.txt
else
  echo "▸ CPU mode (default)."
  pip install --no-cache-dir --timeout 120 -r requirements.txt
fi

# ── 4. Environment file ───────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo "▸ Copying .env.example → .env"
  cp .env.example .env
  echo "  ⚠ Edit .env with your credentials before running the app."
fi

# ── 5. Create media directories ───────────────────────────────────────────────
echo "▸ Creating media directories..."
mkdir -p media/snapshots media/clips models

# ── 6. Download models ────────────────────────────────────────────────────────
echo "▸ Downloading detection models (this may take a few minutes)..."
python scripts/download_models.py

# ── 7. Database migration ─────────────────────────────────────────────────────
echo "▸ Running database migrations..."
echo "  (Make sure PostgreSQL is running and DATABASE_URL in .env is correct)"
source .env 2>/dev/null || true
alembic upgrade head && echo "  ✔ Migrations applied." || echo "  ⚠ Migration failed — is the DB running?"

# ── 8. Done ───────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Setup complete!                                     ║"
echo "║                                                      ║"
echo "║  Next steps:                                         ║"
echo "║  1. Edit .env with your DB/Redis/SMTP/Discord creds  ║"
echo "║  2. Start Redis + PostgreSQL (or: docker compose up) ║"
echo "║  3. Run app:    python run.py                         ║"
echo "║  4. Run worker: celery -A app.alerts.celery_app      ║"
echo "║                        worker --loglevel=info        ║"
echo "║  5. Access:     Follow the URL shown in console       ║"
echo "╚══════════════════════════════════════════════════════╝"
