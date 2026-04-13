.PHONY: clean clean-python clean-frontend clean-build

clean: clean-python clean-frontend clean-build
	@echo "Done."

clean-python:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -name "*.pyc" -o -name "*.pyo" -o -name "*.pyd" | xargs rm -f 2>/dev/null; true

clean-frontend:
	rm -rf frontend/dist frontend/node_modules

clean-build:
	rm -rf build dist
