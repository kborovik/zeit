import ast
import inspect
import os
import subprocess
from pathlib import Path

import pytest

from conftest import load_repo_env
from zeit import Graph

ROOT = Path(__file__).resolve().parents[1]
CONFTEST = ROOT / "tests" / "conftest.py"
WORLD = ROOT / "tests" / "e2e_world.py"
ORG_CHART = ROOT / "tests" / "test_e2e_org_chart.py"
AGENTS = ROOT / "AGENTS.md"
MAKEFILE = ROOT / "Makefile"
PYPROJECT = ROOT / "pyproject.toml"
ENV_EXAMPLE = ROOT / ".env.example"
GITIGNORE = ROOT / ".gitignore"
E2E_PY = (CONFTEST, WORLD, ORG_CHART)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_e2e_marker_and_command() -> None:
    pyproject = _source(PYPROJECT)
    makefile = _source(MAKEFILE)
    assert "e2e: live SurrealDB, Gemini, and Logfire" in pyproject
    assert "pytest -m e2e" in makefile
    assert 'pytest -m "not e2e"' in makefile
    assert "brew install surrealdb/tap/surreal" in _source(ROOT / "README.md")


def test_e2e_skips_without_live_keys() -> None:
    source = _source(CONFTEST)
    assert "GEMINI_API_KEY" in source
    assert "GOOGLE_API_KEY" in source
    assert "LOGFIRE_TOKEN" in source
    assert "SURREAL_URL" in source
    assert "brew install surrealdb/tap/surreal" in source
    assert "has_live_keys" in source
    assert "pytest.skip" in source


def test_env_example_names_keys() -> None:
    text = _source(ENV_EXAMPLE)
    assert "GEMINI_API_KEY" in text
    assert "GOOGLE_API_KEY" in text
    assert "LOGFIRE_TOKEN" in text
    assert "SURREAL_URL" in text


def test_dotenv_is_not_committed() -> None:
    lines = [line.strip() for line in _source(GITIGNORE).splitlines()]
    assert ".env" in lines
    assert ".env.example" not in lines
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(ROOT / ".env")],
        cwd=ROOT,
        check=False,
    )
    assert ignored.returncode == 0
    example = subprocess.run(
        ["git", "check-ignore", "-q", str(ENV_EXAMPLE)],
        cwd=ROOT,
        check=False,
    )
    assert example.returncode == 1


def test_e2e_reads_repo_env_before_start() -> None:
    source = _source(CONFTEST)
    assert "def load_repo_env" in source
    configure = source.split("def pytest_configure")[1].split("\ndef ", 1)[0]
    assert configure.index("load_repo_env()") < configure.index("has_live_keys()")
    assert configure.index("load_repo_env()") < configure.index("logfire.configure")


def test_e2e_does_not_own_keys_after_load() -> None:
    source = _source(CONFTEST)
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "LOGFIRE_TOKEN"):
        assert f'os.environ["{key}"]' not in source
        assert f"os.environ['{key}']" not in source
    assert "logfire.configure(service_name=E2E_SERVICE_NAME)" in source
    params = inspect.signature(Graph.__init__).parameters
    assert "token" not in params
    assert "logfire" not in params


def test_load_repo_env_sets_missing_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".env"
    path.write_text("LOGFIRE_TOKEN=fromfile\nGEMINI_API_KEY=gfromfile\n")
    monkeypatch.delenv("LOGFIRE_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    load_repo_env(path)
    assert os.environ["LOGFIRE_TOKEN"] == "fromfile"
    assert os.environ["GEMINI_API_KEY"] == "gfromfile"


def test_load_repo_env_does_not_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".env"
    path.write_text("LOGFIRE_TOKEN=fromfile\n")
    monkeypatch.setenv("LOGFIRE_TOKEN", "fromshell")
    load_repo_env(path)
    assert os.environ["LOGFIRE_TOKEN"] == "fromshell"


def test_load_repo_env_missing_file_is_noop(tmp_path: Path) -> None:
    load_repo_env(tmp_path / ".env")


def test_e2e_configures_logfire_at_process_start() -> None:
    source = _source(CONFTEST)
    world = _source(WORLD)
    assert "def pytest_configure" in source
    assert "logfire.configure" in source
    assert "service_name=E2E_SERVICE_NAME" in source
    assert 'E2E_SERVICE_NAME = "zeit-e2e"' in world
    assert "logfire.instrument_pydantic_ai" in source
    params = inspect.signature(Graph.__init__).parameters
    assert "token" not in params
    assert "logfire" not in params


def test_e2e_pytest_does_not_query_logfire_http() -> None:
    banned = (
        "query_schema_reference",
        "query_run",
        "logfire.pydantic.dev",
        "logfire-api.pydantic.dev",
        "/v1/query",
    )
    for path in E2E_PY:
        source = _source(path)
        for token in banned:
            assert token not in source
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert "httpx" not in imported
        assert "urllib.request" not in imported
        assert "requests" not in imported


def test_agents_md_logfire_mcp_recipe() -> None:
    text = _source(AGENTS)
    assert "query_schema_reference" in text
    assert "query_run" in text
    assert "zeit-e2e" in text
    assert "pytest -m e2e" in text
    assert "Do not query Logfire over HTTP from pytest." in text
    index_schema = text.index("query_schema_reference")
    index_run = text.index("query_run")
    assert index_schema < index_run


def test_org_chart_world_is_synthetic() -> None:
    source = _source(WORLD)
    assert "class SyntheticWorld" in source
    assert "Ada Lovelace" in source
    assert "Acme" in source
    assert "Birch" in source
    org = _source(ORG_CHART)
    assert "pytest.mark.e2e" in org
    assert "add_episode" not in org
    assert "ingested" in org
