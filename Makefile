# .ONESHELL needs GNU Make ≥ 3.82. macOS ships 3.81 (/usr/bin/make); without
# oneshell each recipe line is a separate shell and multi-line recipes lose
# state (e.g. release version assignment). On macOS use Homebrew's gmake:
# brew install make && gmake <target>
ifeq ($(filter oneshell,$(.FEATURES)),)
$(error GNU Make ≥ 3.82 required (this is $(MAKE_VERSION) from $(MAKE)). On macOS: brew install make && gmake <target>)
endif

.EXPORT_ALL_VARIABLES:
.ONESHELL:
.SILENT:

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
MAKEFLAGS += --no-builtin-rules --no-builtin-variables
export PATH := $(abspath .venv)/bin:$(PATH)

default: help

.PHONY: help check lint format test e2e py-update py-reset \
	release major minor patch

###############################################################################
# Python dev (lint / format / types)
###############################################################################

check: lint test ## Run all checks (lint + tests)

# V11 / §C: lint is check-only. Mutating ruff lives on `format`.
lint: .venv ## ruff check + ruff format --check + basedpyright
	$(call header,Running ruff check)
	uv run ruff check
	$(call header,Running ruff format --check)
	uv run ruff format --check
	$(call header,Running basedpyright)
	uv run basedpyright

format: .venv ## ruff format + ruff check --fix
	$(call header,Running ruff format)
	uv run ruff format
	$(call header,Running ruff check --fix)
	uv run ruff check --fix

test: .venv ## Run pytest (exclude e2e)
	$(call header,Running pytest)
	uv run pytest -m "not e2e"

e2e: .venv ## Run live e2e (SurrealDB + Gemini + Logfire)
	started=
	cleanup() {
		if [[ -n "$${started:-}" ]]; then
			kill "$$started" 2>/dev/null || true
			wait "$$started" 2>/dev/null || true
		fi
	}
	trap cleanup EXIT
	case "$${SURREAL_URL-ws://127.0.0.1:8000/rpc}" in
	ws://127.0.0.1:8000/rpc|ws://localhost:8000/rpc)
		if ! (echo >/dev/tcp/127.0.0.1/8000) >/dev/null 2>&1; then
			$(call header,Starting local SurrealDB)
			command -v surreal >/dev/null \
				|| { echo "install SurrealDB: brew install surrealdb/tap/surreal"; exit 1; }
			surreal start \
				--bind 127.0.0.1:8000 \
				--username "$${SURREAL_USER:-root}" \
				--password "$${SURREAL_PASS:-root}" \
				--log warn \
				--no-banner \
				memory >/dev/null 2>&1 &
			started=$$!
			for _ in {1..100}; do
				if (echo >/dev/tcp/127.0.0.1/8000) >/dev/null 2>&1; then
					break
				fi
				kill -0 "$$started" 2>/dev/null \
					|| { echo "surreal exited before listen"; exit 1; }
				sleep 0.05
			done
			(echo >/dev/tcp/127.0.0.1/8000) >/dev/null 2>&1 \
				|| { echo "surreal did not listen on 127.0.0.1:8000"; exit 1; }
		fi
		;;
	esac
	$(call header,Running pytest -m e2e)
	uv run pytest -m e2e

py-update: ## Recreate venv and upgrade locked deps
	uv venv --clear && hash -r && uv sync --upgrade

py-reset: ## Wipe build artifacts and recreate venv from lock
	rm -rf build/ dist/ *.egg-info
	find . -type d -name "__pycache__" -exec rm -rf {} +
	uv venv --clear && hash -r && uv sync --quiet

.venv: uv.lock
	uv venv --clear && hash -r && uv sync

uv.lock: pyproject.toml
	uv lock --upgrade && touch $(@)

###############################################################################
# Release
###############################################################################

# `gmake release <part>` passes the part as an extra goal; pick it out and
# give the part words no-op recipes so make does not try to build them.
part := $(word 1,$(filter major minor patch,$(MAKECMDGOALS)))

release: check ## Bump version, promote CHANGELOG, commit, tag, push; CI publishes GH release
	test -n "$(part)" || { echo "usage: gmake release major|minor|patch"; exit 1; }
	git diff --quiet && git diff --cached --quiet \
		|| { echo "working tree not clean — commit or stash first"; exit 1; }
	$(call header,Checking CHANGELOG Unreleased has shippable bullets)
	./scripts/changelog check
	$(call header,Bumping $(part) version)
	uv version --bump $(part)
	version=$$(uv version --short)
	$(call header,Promoting CHANGELOG Unreleased → v$$version)
	./scripts/changelog promote "$$version"
	git add pyproject.toml uv.lock CHANGELOG.md
	git commit -m "chore: release v$$version"
	git tag "v$$version"
	$(call header,Pushing v$$version tag (CI will check, then publish GH release))
	git push && git push --tags
	echo "$(green)Tagged v$$version — GitHub Actions runs check, then publishes GH release$(reset)"

major minor patch:
	@:

###############################################################################
# Colors and Headers
###############################################################################

TERM := xterm-256color

blue := $$(tput setaf 4)
green := $$(tput setaf 2)
yellow := $$(tput setaf 3)
reset := $$(tput sgr0)

define header
echo "$(blue)==> $(1) <==$(reset)"
endef

help:
	echo "$(blue)Usage: $(green)gmake [recipe]$(reset)"
	echo "$(blue)Recipes:$(reset)"
	awk 'BEGIN {FS = ":.*?## "; sort_cmd = "sort"} /^[a-zA-Z0-9_-]+:.*?## / \
	{ printf "  \033[33m%-10s\033[0m %s\n", $$1, $$2 | sort_cmd; } \
	END {close(sort_cmd)}' $(MAKEFILE_LIST)
