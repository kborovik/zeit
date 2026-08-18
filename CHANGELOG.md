# Changelog

## Unreleased

### Added

- **Package scaffold:** `import zeit` from `src/zeit/` on Python ≥3.14 with uv, ruff, and basedpyright.
- **Dev Makefile:** `gmake check` runs ruff (check-only), basedpyright, and pytest; `gmake format` applies ruff.
- **Keep-a-Changelog release path:** `gmake release` promotes `## Unreleased` to `## [vX.Y.Z] - date`, and tag `v*` GitHub Release notes come from that section.
