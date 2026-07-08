#!/usr/bin/env bash
# make_dmg.sh: package a built .app bundle into a distributable DMG.
#
# Layout: drag-to-Applications window with the app icon on the left, an
# Applications alias on the right, and a "READ ME FIRST.txt" below with
# first-run instructions (the right-click and Open step, needed because
# we ship without a Developer ID cert so Gatekeeper blocks a plain
# double-click on first launch).
#
# Requires: create-dmg (brew install create-dmg)
#
# Usage: make_dmg.sh <path-to-app-bundle> <output-dir> [version]
#   version defaults to the CFBundleShortVersionString read from the
#   app's Info.plist.

set -euo pipefail

APP="${1:?usage: make_dmg.sh <path-to-app-bundle> <output-dir> [version]}"
OUTDIR="${2:?usage: make_dmg.sh <path-to-app-bundle> <output-dir> [version]}"
VERSION="${3:-}"

if [ ! -d "$APP" ]; then
    echo "ERROR: not a directory: $APP" >&2
    exit 1
fi

if ! command -v create-dmg >/dev/null 2>&1; then
    echo "ERROR: create-dmg is not installed. Install it with:" >&2
    echo "  brew install create-dmg" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="$(basename "$APP" .app)"

if [ -z "$VERSION" ]; then
    VERSION=$(defaults read "$APP/Contents/Info" CFBundleShortVersionString 2>/dev/null || echo "unversioned")
fi

DMG_NAME="${APP_NAME}-${VERSION}-arm64.dmg"
DMG_PATH="${OUTDIR}/${DMG_NAME}"

# Stage the DMG source in a temp dir so create-dmg gets exactly the
# files we want and nothing else (avoids picking up stray files if the
# output dir has other artifacts).
STAGE=$(mktemp -d -t wormtracker_dmg.XXXXXX)
trap 'rm -rf "$STAGE"' EXIT

cp -R "$APP" "$STAGE/"
cp "$SCRIPT_DIR/READ ME FIRST.txt" "$STAGE/"

rm -f "$DMG_PATH"
mkdir -p "$OUTDIR"

echo "==> Building DMG: $DMG_PATH"
create-dmg \
    --volname "$APP_NAME $VERSION" \
    --window-pos 200 120 \
    --window-size 640 400 \
    --icon-size 100 \
    --icon "$APP_NAME.app" 160 190 \
    --hide-extension "$APP_NAME.app" \
    --app-drop-link 480 190 \
    --icon "READ ME FIRST.txt" 320 320 \
    --no-internet-enable \
    "$DMG_PATH" \
    "$STAGE"

echo ""
echo "DMG built: $DMG_PATH"
