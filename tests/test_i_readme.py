from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

PITCH_HEADINGS = (
    "# Bi-Temporal Knowledge Graph",
    "## Two clocks",
    "## What you do with it",
)

DROPPED_HEADINGS = (
    "## Intended shape",
    "## Run from this repo",
    "## Release",
    "## How it runs",
    "## Status",
)

HOWTO_TOKENS = (
    "zeit-graph",
    "Graph",
    "add_episode",
    "add_triplet",
    "search",
    "get_entity",
    "get_fact",
    "valid_at",
    "invalid_at",
    "created_at",
    "expired_at",
    "ModelStack",
    "logfire.configure",
    "logfire.instrument_pydantic_ai",
    "GEMINI_API_KEY",
    "namespace",
    "database",
)

MAINTAINER_TOKENS = (
    "gmake release",
    "gmake check",
    "brew install surrealdb",
    "gh release create",
    "uv publish",
)


def test_readme_keeps_pitch() -> None:
    text = README.read_text(encoding="utf-8")
    for heading in PITCH_HEADINGS:
        assert heading in text


def test_readme_drops_maintainer_sections() -> None:
    text = README.read_text(encoding="utf-8")
    for heading in DROPPED_HEADINGS:
        assert heading not in text
    for token in MAINTAINER_TOKENS:
        assert token not in text


def test_readme_after_pitch_is_agent_howto() -> None:
    text = README.read_text(encoding="utf-8")
    after = text.split("## What you do with it", maxsplit=1)[1]
    for token in HOWTO_TOKENS:
        assert token in after
