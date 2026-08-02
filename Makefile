.RECIPEPREFIX := >

SHELL := /bin/sh
PYTHON ?= python3

.PHONY: validate validate-manifests

validate: validate-manifests

validate-manifests:
> $(PYTHON) scripts/validate-kubernetes-manifests.py --check all
