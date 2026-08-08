#!/usr/bin/env bash
# build.sh: Build ParaTracker.app
# Usage: ./build.sh
# Env: VENV overrides the virtualenv path (defaults to $HOME/venv/worm-tracker).
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

: "${VENV:=$HOME/venv/worm-tracker}"
echo "==> Activating Python virtual environment ($VENV)"
if [ ! -f "$VENV/bin/activate" ]; then
    echo "ERROR: virtualenv not found at $VENV. Run 'make venv' first." >&2
    exit 1
fi
source "$VENV/bin/activate"

echo "==> Ensuring build deps are installed"
pip install pyinstaller imageio-ffmpeg -q

echo "==> Building React frontend (production, relative URLs)"
cd frontend
npm install
VITE_API_URL="" npm run build
cd "$PROJECT_DIR"

echo "==> Running PyInstaller"
pyinstaller worm_tracker.spec --clean --noconfirm

echo "==> Ad-hoc signing the app bundle"
"$PROJECT_DIR/scripts/sign_app.sh" "$PROJECT_DIR/dist/ParaTracker.app"

echo ""
echo "Build complete!"
echo "  App bundle : dist/ParaTracker.app"
echo "  Launch     : open dist/ParaTracker.app"
echo ""
echo "  Or run directly (shows server logs):"
echo "  dist/ParaTracker/ParaTracker"
