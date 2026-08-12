PYTHON ?= python3
VENV := .venv
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
UVICORN := $(VENV)/bin/uvicorn

.PHONY: setup test dev clean-test-db reset-local-db

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

test:
	EMPTY_CHAIR_DB=test_empty_chair.db \
	EMPTY_CHAIR_DEMO_MODE=true \
	EMPTY_CHAIR_SESSION_SECRET=test-secret \
	$(PYTEST) -q

dev:
	EMPTY_CHAIR_DB=local_empty_chair.db \
	EMPTY_CHAIR_DEMO_MODE=true \
	EMPTY_CHAIR_SESSION_SECRET=local-dev-secret \
	EMPTY_CHAIR_BASE_URL=http://127.0.0.1:8000 \
	$(UVICORN) app:app --reload --host 127.0.0.1 --port 8000

clean-test-db:
	rm -f test_empty_chair.db

reset-local-db:
	rm -f local_empty_chair.db
