PY ?= python

.PHONY: install run test lint typecheck check sources deploy logs

install:
	$(PY) -m pip install -e ".[all,dev]"

run:
	$(PY) -m app

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check app tests scripts
	$(PY) -m ruff format --check app tests scripts

typecheck:
	$(PY) -m mypy

check: lint typecheck test

sources:
	$(PY) scripts/check_sources.py

deploy:
	git pull --ff-only
	docker compose build
	docker compose up -d
	docker compose ps

logs:
	docker compose logs -f --tail=200 bot
