import inspect
import sys
import tomllib
from pathlib import Path
from typing import cast

import zeit
from zeit import Graph
from zeit.embedder import DEFAULT_EMBEDDER_MODEL
from zeit.graph import DEFAULT_MODEL

ROOT = Path(__file__).resolve().parents[1]


def _table(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _pyproject() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return _table(tomllib.load(fh))


def test_requires_python_at_least_3_14() -> None:
    project = _table(_pyproject()["project"])
    assert project["requires-python"] == ">=3.14"
    assert sys.version_info >= (3, 14)


def test_import_zeit_from_src() -> None:
    package_file = zeit.__file__
    assert package_file is not None
    package_dir = Path(package_file).resolve().parent
    assert package_dir == (ROOT / "src" / "zeit").resolve()


def test_ruff_targets_py314() -> None:
    ruff = _table(_table(_pyproject()["tool"])["ruff"])
    assert ruff["target-version"] == "py314"


def test_basedpyright_strict() -> None:
    basedpyright = _table(_table(_pyproject()["tool"])["basedpyright"])
    assert basedpyright["typeCheckingMode"] == "strict"
    assert basedpyright["pythonVersion"] == "3.14"


def test_makefile_lint_is_check_only() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "ruff check" in makefile
    assert "ruff format --check" in makefile
    assert "basedpyright" in makefile


def _runtime_deps() -> list[str]:
    project = _table(_pyproject()["project"])
    raw = project["dependencies"]
    assert isinstance(raw, list)
    deps: list[str] = []
    for item in cast(list[object], raw):
        assert isinstance(item, str)
        deps.append(item)
    return deps


def test_runtime_dep_is_pydantic_ai_slim_google() -> None:
    deps = _runtime_deps()
    pydantic_ai = [item for item in deps if item.startswith("pydantic-ai")]
    assert len(pydantic_ai) == 1
    spec = pydantic_ai[0]
    assert spec.startswith("pydantic-ai-slim[google]")
    for extra in ("cli", "openai", "anthropic"):
        assert extra not in spec.lower()


def test_runtime_dep_includes_logfire() -> None:
    deps = _runtime_deps()
    logfire = [item for item in deps if item.startswith("logfire")]
    assert len(logfire) == 1


def test_library_does_not_own_logfire_or_model_token() -> None:
    params = inspect.signature(Graph.__init__).parameters
    assert "token" not in params
    assert "api_key" not in params
    assert "logfire" not in params
    for path in (ROOT / "src" / "zeit").rglob("*.py"):
        assert "LOGFIRE_TOKEN" not in path.read_text(encoding="utf-8")


def test_default_gemini_path_reads_gemini_key() -> None:
    assert DEFAULT_MODEL.startswith("google:")
    assert DEFAULT_EMBEDDER_MODEL.startswith("google:")
    from pydantic_ai.providers import google as google_provider

    source = Path(google_provider.__file__).read_text(encoding="utf-8")
    assert "GEMINI_API_KEY" in source
