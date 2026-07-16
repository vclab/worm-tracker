#!/usr/bin/env bash
# make_dmg.sh: package a built .app bundle into a distributable DMG.
#
# Uses plain hdiutil (built into macOS, no Homebrew dependency). The DMG
# contains the app, a symlink to /Applications for drag-to-install, and
# a "READ ME FIRST.txt" with first-launch instructions.
#
# We deliberately avoid create-dmg here: its final unmount step fails
# intermittently on macOS 13+ with "Resource busy" because Finder or
# fseventsd holds a handle on the mounted RW volume after the layout
# AppleScript runs. `hdiutil create -srcfolder` bypasses the whole
# mount/unmount cycle by building the compressed DMG directly from a
# staging directory.
#
# Tradeoff: no custom icon positions or background image. The Applications
# symlink still gives a working drag-to-install workflow.
#
# Usage: make_dmg.sh <path-to-app-bundle> <output-dir> [version]

set -euo pipefail

APP="${1:?usage: make_dmg.sh <path-to-app-bundle> <output-dir> [version]}"
OUTDIR="${2:?usage: make_dmg.sh <path-to-app-bundle> <output-dir> [version]}"
VERSION="${3:-}"

if [ ! -d "$APP" ]; then
    echo "ERROR: not a directory: $APP" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="$(basename "$APP" .app)"

if [ -z "$VERSION" ]; then
    VERSION=$(defaults read "$APP/Contents/Info" CFBundleShortVersionString 2>/dev/null || echo "unversioned")
fi

DMG_NAME="${APP_NAME}-${VERSION}-arm64.dmg"
DMG_PATH="${OUTDIR}/${DMG_NAME}"
VOL_NAME="${APP_NAME} ${VERSION}"

STAGE=$(mktemp -d -t paratracker_dmg.XXXXXX)
trap 'rm -rf "$STAGE"' EXIT

echo "==> Staging DMG contents"
cp -R "$APP" "$STAGE/"
cp "$SCRIPT_DIR/READ ME FIRST.txt" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

mkdir -p "$OUTDIR"
rm -f "$DMG_PATH"

echo "==> Building DMG: $DMG_PATH"
hdiutil create \
    -volname "$VOL_NAME" \
    -srcfolder "$STAGE" \
    -ov \
    -format UDZO \
    -imagekey zlib-level=9 \
    "$DMG_PATH"

echo ""
echo "DMG built: $DMG_PATH"
