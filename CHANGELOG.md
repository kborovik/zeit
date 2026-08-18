# Changelog

## Unreleased

### Added

- **Swappable embedder:** `Embedder` protocol plus a PydanticAI implementation; callers may supply their own.
- **Closed types:** `Episode`, `Entity`, `Fact`, `Mention`, `IngestResult`, and `SearchHits` are frozen dataclasses with no tenant field.
- **Package scaffold:** `import zeit` from `src/zeit/` on Python ≥3.14 with uv, ruff, and basedpyright.
- **Dev Makefile:** `gmake check` runs ruff (check-only), basedpyright, and pytest; `gmake format` applies ruff.
- **Keep-a-Changelog release path:** `gmake release` promotes `## Unreleased` to `## [vX.Y.Z] - date`, and tag `v*` GitHub Release notes come from that section.
