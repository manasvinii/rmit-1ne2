.PHONY: install test run ingest eval lint clean

PY ?= .venv/bin/python

install:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

test:
	$(PY) -m pytest -q

run:
	$(PY) -m uvicorn app.main:app --reload --port 8010

# make ingest USER=3999001 COURSE=COSC2673 DIR=/path/to/lectures
ingest:
	$(PY) -m app.cli ingest --user-id $(USER) --course-id $(COURSE) --dir $(DIR)

# make eval USER=3999001
eval:
	$(PY) -m eval.run_eval --user-id $(USER) --dataset eval/datasets/cosc2673_seed.jsonl --include-draft

lint:
	$(PY) -m ruff check app tests eval

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__
