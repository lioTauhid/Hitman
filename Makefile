# Hitman: common development tasks.
#
# Works with GNU make on macOS, Linux and Windows (Git Bash, MSYS2, or make from Chocolatey/Scoop).
# File operations go through Python so the recipes don't depend on a Unix shell.
#
#   make            list the targets
#   make run        set everything up on first use, then start the app

VENV := .venv

ifeq ($(OS),Windows_NT)
    PYTHON ?= python
    PY := $(VENV)/Scripts/python.exe
else
    PYTHON ?= python3
    PY := $(VENV)/bin/python
endif

# Re-installs when the dependencies change.
STAMP := $(VENV)/.installed

.DEFAULT_GOAL := help
.PHONY: help venv install run test lint check build package clean distclean

help: ## List the available targets
	@"$(PYTHON)" -c "import re; print('Usage: make <target>\n'); [print(f'  {t:<10} {d}') for t, d in re.findall(r'^([a-z]+):.*?## (.*)$$', open('Makefile', encoding='utf-8').read(), re.M)]"

$(PY):
	"$(PYTHON)" -m venv $(VENV)

# Environments made by other tools (e.g. uv) may lack pip, so bootstrap it when missing.
$(STAMP): pyproject.toml | $(PY)
	"$(PY)" -m pip --version || "$(PY)" -m ensurepip --upgrade
	"$(PY)" -m pip install -e ".[dev]"
	"$(PY)" -c "import pathlib; pathlib.Path('$(STAMP)').touch()"

venv: $(PY) ## Create the virtual environment (.venv)

install: $(STAMP) ## Install the app and dev tools into .venv

run: $(STAMP) ## Start the app
	"$(PY)" -m hitman

test: $(STAMP) ## Run the test suite
	"$(PY)" -m pytest

lint: $(STAMP) ## Check the code with pyflakes
	"$(PY)" -m pyflakes hitman tests scripts

check: lint test ## Lint, then test

build: $(STAMP) ## Build the standalone app and a portable archive into dist/
	"$(PY)" -m pip install -e ".[build]"
	"$(PY)" scripts/build.py

package: $(STAMP) ## Build, plus this OS's installer (Windows setup.exe, Linux .deb)
	"$(PY)" -m pip install -e ".[build]"
	"$(PY)" scripts/build.py --package

clean: ## Remove build output and caches
	"$(PYTHON)" -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in ['build', 'dist', '.pytest_cache', 'hitman.egg-info']]; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__') if '$(VENV)' not in p.parts]"

distclean: clean ## Also remove the virtual environment
	"$(PYTHON)" -c "import shutil; shutil.rmtree('$(VENV)', ignore_errors=True)"
