.PHONY: dist build run clean clean-python clean-python-env clean-frontend clean-build check-npm venv

SHELL := /bin/bash
VENV := $(HOME)/venv/worm-tracker
PIP_STAMP := $(VENV)/.requirements-stamp

dist: clean venv
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

run: check-npm frontend/node_modules/.install-stamp $(PIP_STAMP)
	@lsof -ti:8000 | xargs kill -9 2>/dev/null; true
	@trap 'kill 0' INT TERM EXIT; \
		source "$(VENV)/bin/activate" && \
		uvicorn app.main:app --reload --port 8000 & \
		npm --prefix frontend run dev; \
		wait

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
