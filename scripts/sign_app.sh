#!/usr/bin/env bash
# sign_app.sh: ad-hoc sign a macOS .app bundle.
#
# Ad-hoc signing (identity "-") does NOT satisfy Gatekeeper; users will
# still need to right-click and choose Open on first launch. What it DOES
# do is give every embedded binary a consistent internal signature, which
# prevents "code signature invalid" or "library not loaded" errors on
# macOS 11+ where the OS rejects unsigned dylibs loaded by a signed
# process.
#
# Usage: sign_app.sh <path-to-app-bundle> [identity]
#   identity defaults to "-" (ad-hoc). Pass a Developer ID Application
#   identity string to do real signing once a cert is available.

set -euo pipefail

APP="${1:?usage: sign_app.sh <path-to-app-bundle> [identity]}"
IDENTITY="${2:--}"

if [ ! -d "$APP" ]; then
    echo "ERROR: not a directory: $APP" >&2
    exit 1
fi

echo "==> Signing $APP (identity: $IDENTITY)"

# --deep is deprecated for proper Developer ID signing (each binary
# should be signed with its own entitlements), but for ad-hoc signing
# where every binary gets the same (empty) entitlements it is the
# simplest and correct choice.
codesign --force --deep --sign "$IDENTITY" --timestamp=none "$APP"

echo "==> Verifying signature"
codesign --verify --verbose=2 "$APP"

echo "Signed."
