.RECIPEPREFIX := >

VENV ?= .venv
PYTHON ?= $(VENV)/bin/python

.PHONY: validate validate-cratecheck validate-vanilla-composition

validate: $(PYTHON) validate-cratecheck validate-vanilla-composition

$(PYTHON): requirements-dev.txt
> python3 -m venv $(VENV)
> $(PYTHON) -m pip install -r requirements-dev.txt

validate-cratecheck:
> $(PYTHON) tests/validate-cratecheck.py

validate-vanilla-composition:
> $(PYTHON) tests/validate-vanilla-composition.py
