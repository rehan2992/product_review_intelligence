PYTHON ?= python3
VENV ?= .venv
PY = $(VENV)/bin/python

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements.txt

data:
	$(PY) -m src.generate_data --out data/sample

run:
	$(PY) -m src.pipeline --reset

# Demonstrates incremental loading: batch 1, then batch 2 (overlapping)
demo-incremental:
	$(PY) -m src.pipeline --reset --files batch_1.csv
	$(PY) -m src.pipeline --files batch_2.csv
	$(PY) -m src.pipeline --files batch_1.csv batch_2.csv   # re-run: nothing changes

test:
	$(PY) -m pytest -q

.PHONY: setup data run demo-incremental test
