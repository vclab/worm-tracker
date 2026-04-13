.PHONY: dist build run clean clean-python clean-frontend clean-build

SHELL := /bin/bash

dist: clean
	./build.sh

build: frontend/node_modules/.install-stamp

frontend/node_modules/.install-stamp: frontend/package.json
	cd frontend && npm install
	@touch frontend/node_modules/.install-stamp

run: frontend/node_modules/.install-stamp
	@lsof -ti:8000 | xargs kill -9 2>/dev/null; true
	@trap 'kill 0' INT TERM EXIT; \
		source ~/venv/worm-tracker/bin/activate && \
		uvicorn app.main:app --reload --port 8000 & \
		npm --prefix frontend run dev; \
		wait

clean: clean-python clean-frontend clean-build
	@echo "Done."

clean-python:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -name "*.pyc" -o -name "*.pyo" -o -name "*.pyd" | xargs rm -f 2>/dev/null; true

clean-frontend:
	rm -rf frontend/dist frontend/node_modules

clean-build:
	rm -rf build dist
