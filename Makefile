PYTHON ?= python
VENV ?= backend/.venv
VENV_PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: venv env-check seed

venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -r backend/requirements.txt

env-check:
	$(PYTHON) scripts/check_env.py

seed:
	$(PYTHON) scripts/seed.py --n $(or $(N),100000)
