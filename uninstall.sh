#!/usr/bin/env bash
# =============================================================================
# Campus Eye — Uninstall Script
# Removes the virtual environment, downloaded models, generated media,
# Docker containers/volumes, and optionally the database.
#
# Usage:
#   bash uninstall.sh              # interactive (asks before each step)
#   bash uninstall.sh --all        # remove everything without prompting
#   bash uninstall.sh --keep-db    # remove everything except the database
#   bash uninstall.sh --dry-run    # show what WOULD be removed, do nothing
# =============================================================================
set -e

ALL=false
KEEP_DB=false
DRY_RUN=false

for arg in "$@"; do
  case $arg in
    --all)     ALL=true ;;
    --keep-db) KEEP_DB=true ;;
    --dry-run) DRY_RUN=true ;;
  esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────

RED='\033[0;31m'
YEL='\033[1;33m'
GRN='\033[0;32m'
NC='\033[0m'

log()  { echo -e "${GRN}▸${NC} $1"; }
warn() { echo -e "${YEL}⚠${NC}  $1"; }
err()  { echo -e "${RED}✗${NC}  $1"; }

run() {
  # $1 = description, $2+ = command
  local desc="$1"; shift
  if [ "$DRY_RUN" = true ]; then
    echo "  [dry-run] would run: $*"
    return
  fi
  log "$desc"
  "$@" || warn "Command failed (continuing): $*"
}

confirm() {
  # Returns 0 (yes) or 1 (no)
  if [ "$ALL" = true ]; then return 0; fi
  read -rp "  $1 [y/N] " answer
  case "$answer" in [yY]*) return 0 ;; *) return 1 ;; esac
}

echo ""
echo -e "${RED}╔══════════════════════════════════════════════╗${NC}"
echo -e "${RED}║      Campus Eye — Uninstall Script           ║${NC}"
echo -e "${RED}╚══════════════════════════════════════════════╝${NC}"
echo ""

if [ "$DRY_RUN" = true ]; then
  warn "DRY RUN MODE — nothing will actually be deleted."
  echo ""
fi

# ── 1. Stop Docker services ───────────────────────────────────────────────────
if command -v docker &>/dev/null && [ -f "docker-compose.yml" ]; then
  if confirm "Stop and remove Docker containers?"; then
    run "Stopping Docker containers..." docker compose down

    if [ "$KEEP_DB" = false ]; then
      if confirm "Remove Docker volumes (DELETES ALL DATABASE DATA)?"; then
        run "Removing Docker volumes..." docker compose down --volumes --remove-orphans
      fi
    else
      log "Keeping Docker volumes (--keep-db specified)."
    fi
  fi
else
  log "Docker Compose not found or no docker-compose.yml — skipping."
fi

# ── 2. Drop PostgreSQL database (local, non-Docker) ──────────────────────────
if [ "$KEEP_DB" = false ]; then
  if confirm "Drop local PostgreSQL database 'campus_eye'? (only if running locally, not Docker)"; then
    if command -v psql &>/dev/null; then
      run "Dropping database..." \
        sudo -u postgres psql -c "DROP DATABASE IF EXISTS campus_eye;" \
        -c "DROP ROLE IF EXISTS campus_eye;"
    else
      warn "psql not found — skipping local DB drop."
    fi
  fi
fi

# ── 3. Remove virtual environment ─────────────────────────────────────────────
if [ -d "venv" ]; then
  if confirm "Remove Python virtual environment (./venv)?"; then
    run "Removing venv..." rm -rf venv
  fi
else
  log "No venv found — skipping."
fi

# ── 4. Remove downloaded model weights ───────────────────────────────────────
if [ -d "models" ]; then
  MODEL_SIZE=$(du -sh models 2>/dev/null | cut -f1)
  if confirm "Remove downloaded model weights (./models — ${MODEL_SIZE})?"; then
    run "Removing models..." rm -rf models
  fi
else
  log "No models directory found — skipping."
fi

# ── 5. Remove generated media files ──────────────────────────────────────────
if [ -d "media" ]; then
  MEDIA_SIZE=$(du -sh media 2>/dev/null | cut -f1)
  if confirm "Remove generated media files (./media — snapshots, clips — ${MEDIA_SIZE})?"; then
    run "Removing media..." rm -rf media
  fi
else
  log "No media directory found — skipping."
fi

# ── 6. Remove registered face photos ─────────────────────────────────────────
if [ -d "media/photos" ] || find . -name "*.jpg" -path "*/photos/*" &>/dev/null; then
  if confirm "Remove registered face photos?"; then
    run "Removing face photos..." rm -rf media/photos
  fi
fi

# ── 7. Remove .env file (secrets) ────────────────────────────────────────────
if [ -f ".env" ]; then
  if confirm "Remove .env file (contains credentials)?"; then
    run "Removing .env..." rm -f .env
  fi
else
  log "No .env file found — skipping."
fi

# ── 8. Remove Python cache files ─────────────────────────────────────────────
if confirm "Remove Python __pycache__ and .pyc files?"; then
  run "Cleaning Python cache..." \
    find . -type d -name "__pycache__" -not -path "./venv/*" -exec rm -rf {} + 2>/dev/null || true
  run "Cleaning .pyc files..." \
    find . -name "*.pyc" -not -path "./venv/*" -delete 2>/dev/null || true
  run "Cleaning .pytest_cache..." rm -rf .pytest_cache
fi

# ── 9. Remove YOLO weight files cached in home dir ───────────────────────────
YOLO_CACHE="$HOME/.config/Ultralytics"
if [ -d "$YOLO_CACHE" ]; then
  if confirm "Remove Ultralytics/YOLO cache (~/.config/Ultralytics)?"; then
    run "Removing YOLO cache..." rm -rf "$YOLO_CACHE"
  fi
fi

# ── 10. Remove InsightFace cache ──────────────────────────────────────────────
INSIGHTFACE_CACHE="$HOME/.insightface"
if [ -d "$INSIGHTFACE_CACHE" ]; then
  if confirm "Remove InsightFace model cache (~/.insightface)?"; then
    run "Removing InsightFace cache..." rm -rf "$INSIGHTFACE_CACHE"
  fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
if [ "$DRY_RUN" = true ]; then
  echo -e "${YEL}Dry run complete. No files were deleted.${NC}"
else
  echo -e "${GRN}╔══════════════════════════════════════════════════╗${NC}"
  echo -e "${GRN}║  Campus Eye uninstall complete.                  ║${NC}"
  echo -e "${GRN}║  Source code and config files have been kept.    ║${NC}"
  echo -e "${GRN}║  To reinstall: bash setup.sh                     ║${NC}"
  echo -e "${GRN}╚══════════════════════════════════════════════════╝${NC}"
fi
echo ""
