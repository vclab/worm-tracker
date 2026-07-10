.PHONY: dist build run clean clean-python clean-python-env clean-frontend clean-build clean-weights check-npm venv weights dmg release

SHELL := /bin/bash
VENV := $(HOME)/venv/worm-tracker
PIP_STAMP := $(VENV)/.requirements-stamp

# Version is read from the PyInstaller spec so there is one source of truth.
# Update CFBundleShortVersionString in worm_tracker.spec to bump.
VERSION := $(shell grep 'CFBundleShortVersionString' worm_tracker.spec | head -1 | sed 's/.*"\([0-9.]*\)".*/\1/')

# YOLO weights — content-hashed filename so the SHA256 in the path is the
# integrity check. To swap models, change both WEIGHTS_SHA256 and
# WEIGHTS_GDRIVE_ID here, and keep DEFAULT_WEIGHTS_SHA256 in app/main.py in sync.
WEIGHTS_DIR := weights
WEIGHTS_SHA256 := f7712cb708c94a788f36fe8cbf9c1f479e399286ab3c9afbbb318e4c6d9f80fe
WEIGHTS_FILE := $(WEIGHTS_DIR)/worm_yolov8seg-$(WEIGHTS_SHA256).pt
WEIGHTS_GDRIVE_ID := 1s9IiJdX9vUkwJ9MOFV1rZDEWsKyk_ofk

dist: clean venv weights
	./build.sh

build: check-npm frontend/node_modules/.install-stamp

check-npm:
	@if ! command -v npm >/dev/null 2>&1; then \
		echo ""; \
		echo "ERROR: npm is not installed or not on PATH."; \
		echo ""; \
		echo "Please install Node.js (which includes npm) yourself:"; \
		echo "  - Download from https://nodejs.org/"; \
		echo "  - Or on macOS via Homebrew: brew install node"; \
		echo ""; \
		exit 1; \
	fi

venv: $(PIP_STAMP)

$(PIP_STAMP): requirements.txt
	@if ! command -v python3 >/dev/null 2>&1; then \
		echo "ERROR: python3 is not installed or not on PATH."; \
		exit 1; \
	fi
	@if [ ! -f "$(VENV)/bin/activate" ]; then \
		echo "Creating Python virtual environment at $(VENV)..."; \
		mkdir -p "$(dir $(VENV))"; \
		python3 -m venv "$(VENV)"; \
	fi
	@echo "Installing Python requirements into $(VENV)..."
	@source "$(VENV)/bin/activate" && pip install -r requirements.txt
	@touch "$(PIP_STAMP)"

frontend/node_modules/.install-stamp: frontend/package.json | check-npm
	cd frontend && npm install
	@touch frontend/node_modules/.install-stamp

run: check-npm frontend/node_modules/.install-stamp $(PIP_STAMP) $(WEIGHTS_FILE)
	@lsof -ti:8000 | xargs kill -9 2>/dev/null; true
	@trap 'kill 0' INT TERM EXIT; \
		source "$(VENV)/bin/activate" && \
		uvicorn app.main:app --reload --port 8000 & \
		npm --prefix frontend run dev; \
		wait

weights: $(WEIGHTS_FILE)

$(WEIGHTS_FILE): $(PIP_STAMP)
	@mkdir -p $(WEIGHTS_DIR)
	@echo "Downloading YOLO weights from Google Drive (id=$(WEIGHTS_GDRIVE_ID))..."
	@TMP=$$(mktemp -t worm_yolov8seg.XXXXXX) && \
		source "$(VENV)/bin/activate" && \
		python -m gdown "$(WEIGHTS_GDRIVE_ID)" -O "$$TMP" && \
		ACTUAL_SHA=$$(shasum -a 256 "$$TMP" | awk '{print $$1}') && \
		if [ "$$ACTUAL_SHA" != "$(WEIGHTS_SHA256)" ]; then \
			echo "ERROR: SHA256 mismatch for downloaded weights."; \
			echo "  expected: $(WEIGHTS_SHA256)"; \
			echo "  actual:   $$ACTUAL_SHA"; \
			rm -f "$$TMP"; \
			exit 1; \
		fi && \
		mv "$$TMP" "$(WEIGHTS_FILE)" && \
		echo "Weights verified and saved to $(WEIGHTS_FILE)"

clean: clean-python clean-frontend clean-build
	@echo "Done."

clean-python:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -name "*.pyc" -o -name "*.pyo" -o -name "*.pyd" | xargs rm -f 2>/dev/null; true

clean-python-env:
	@if [ -d "$(VENV)" ]; then \
		echo "Removing Python virtual environment at $(VENV)..."; \
		rm -rf "$(VENV)"; \
	else \
		echo "No virtual environment at $(VENV) — nothing to remove."; \
	fi

clean-frontend:
	rm -rf frontend/dist frontend/node_modules

clean-build:
	rm -rf build dist

clean-weights:
	rm -rf $(WEIGHTS_DIR)

# ---------------------------------------------------------------------------
# Release packaging (macOS DMG)
# ---------------------------------------------------------------------------

# Package the already-built dist/ParaTracker.app into a DMG. Assumes
# `make dist` has already run (build.sh also ad-hoc signs the app).
# Uses hdiutil (built into macOS), no extra deps required.
dmg:
	@if [ ! -d dist/ParaTracker.app ]; then \
		echo "ERROR: dist/ParaTracker.app not found. Run 'make dist' first."; \
		exit 1; \
	fi
	./scripts/make_dmg.sh dist/ParaTracker.app dist $(VERSION)

# Full release: clean rebuild + sign (via build.sh) + DMG.
release: dist
	$(MAKE) dmg
	@echo ""
	@echo "Release artifact: dist/ParaTracker-$(VERSION)-arm64.dmg"
