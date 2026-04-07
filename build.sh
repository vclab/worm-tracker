#!/usr/bin/env bash
# build.sh — Build WormTracker.app
# Usage: ./build.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "==> Activating Python virtual environment"
source ~/venv/worm-tracker/bin/activate

echo "==> Ensuring build deps are installed"
pip install pyinstaller imageio-ffmpeg -q

echo "==> Building React frontend (production, relative URLs)"
cd frontend
npm install
VITE_API_URL="" npm run build
cd "$PROJECT_DIR"

echo "==> Running PyInstaller"
pyinstaller worm_tracker.spec --clean --noconfirm

echo ""
echo "Build complete!"
echo "  App bundle : dist/WormTracker.app"
echo "  Launch     : open dist/WormTracker.app"
echo ""
echo "  Or run directly (shows server logs):"
echo "  dist/WormTracker/WormTracker"
