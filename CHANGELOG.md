# Changelog

## Unreleased

### Changed

- **Default models:** `Graph` no longer requires a `ModelStack`; extract, resolve, and invalidate default to `google:gemini-3.7-flash`; the embedder defaults to `google:gemini-embedding-2`.
- **PydanticAI slim:** runtime dependency is `pydantic-ai-slim[google]` only; unused extras (CLI, OpenAI, Anthropic) are dropped.

### Added

- **E2e env file:** copy `.env.example` to `.env`; the harness loads it before start so keys need not be exported in the shell.
- **E2e:** `pytest -m e2e` ingests an org-chart SyntheticWorld against brew SurrealDB with live Gemini; the harness configures Logfire at process start; pytest asserts the graph only.
- **Logfire traces:** extract, resolve, invalidate, and embed calls emit OpenTelemetry spans so they appear in Logfire when the caller has configured it; `Graph` does not take a token.
- **Hybrid search:** `Graph.search` embeds the query, fuses vector and full-text ranks with reciprocal rank fusion, expands one hop, and defaults to facts that are valid now.
- **Uuid getters:** `Graph.get_entity` and `Graph.get_fact` return a stored record or `None`.
- **Known facts:** `Graph.add_triplet` writes a subject-predicate-object claim without extract, then resolves, invalidates, embeds, and persists.
- **Graph ingest:** `Graph.add_episode` runs context, extract, resolve, invalidate, embed, and persist, then returns `IngestResult`.
- **Invalidate:** a contradicting claim expires the old fact in place and keeps both world time and transaction time on the row.
- **Resolve:** match extracted surface forms to existing entities so two names for the same thing share one uuid.
- **Context window:** fetch the last N episodes (default 3) in chronological order for extract and resolve.
- **Extract agents:** first-party PydanticAI agents pull entities and facts from an episode.
- **SurrealDB store:** `Store` protocol plus a SurrealDB schema and implementation bound to one namespace and database.
- **Swappable embedder:** `Embedder` protocol plus a PydanticAI implementation; callers may supply their own.
- **Closed types:** `Episode`, `Entity`, `Fact`, `Mention`, `IngestResult`, and `SearchHits` are frozen dataclasses with no tenant field.
- **Package scaffold:** `import zeit` from `src/zeit/` on Python ≥3.14 with uv, ruff, and basedpyright.
- **Dev Makefile:** `gmake check` runs ruff (check-only), basedpyright, and pytest; `gmake format` applies ruff.
- **Keep-a-Changelog release path:** `gmake release` promotes `## Unreleased` to `## [vX.Y.Z] - date`, and tag `v*` GitHub Release notes come from that section.
