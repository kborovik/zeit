"""Brew SurrealDB ≥3 fixtures, e2e Logfire, org-chart world."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import pytest
import pytest_asyncio

from e2e_world import (
    E2E_NAMESPACE,
    E2E_SERVICE_NAME,
    IngestedWorld,
    SyntheticWorld,
)
from zeit import Graph, IngestResult, ModelStack, SurrealStore

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_ENV = REPO_ROOT / ".env"
DEFAULT_SURREAL_URL = "ws://127.0.0.1:8000/rpc"


def load_repo_env(path: Path | None = None) -> None:
    env_path = REPO_ENV if path is None else path
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def has_live_keys() -> bool:
    has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    has_logfire = bool(os.environ.get("LOGFIRE_TOKEN"))
    return has_gemini and has_logfire


def resolve_surreal_url() -> str | None:
    if "SURREAL_URL" in os.environ:
        value = os.environ["SURREAL_URL"].strip()
        return value or None
    return DEFAULT_SURREAL_URL


def _e2e_deselected(config: pytest.Config) -> bool:
    expr = (getattr(config.option, "markexpr", "") or "").replace(" ", "")
    return "note2e" in expr


def pytest_configure(config: pytest.Config) -> None:
    if _e2e_deselected(config):
        return
    load_repo_env()
    if not has_live_keys():
        return
    import logfire

    logfire.configure(service_name=E2E_SERVICE_NAME)


def surreal_credentials() -> dict[str, str]:
    return {
        "username": os.environ.get("SURREAL_USER", "root"),
        "password": os.environ.get("SURREAL_PASS", "root"),
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(host: str, port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"surreal did not listen on {host}:{port}")


def _url_listening(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8000
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def _start_brew_surreal() -> Iterator[str]:
    binary = shutil.which("surreal")
    if binary is None:
        pytest.skip("install SurrealDB: brew install surrealdb/tap/surreal")
    port = _free_port()
    proc = subprocess.Popen(
        [
            binary,
            "start",
            "--bind",
            f"127.0.0.1:{port}",
            "--username",
            "root",
            "--password",
            "root",
            "--log",
            "warn",
            "--no-banner",
            "memory",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port("127.0.0.1", port)
        yield f"ws://127.0.0.1:{port}/rpc"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _managed_surreal_url() -> Iterator[str]:
    existing = resolve_surreal_url()
    if existing is None:
        yield from _start_brew_surreal()
        return
    if _url_listening(existing):
        yield existing
        return
    if "SURREAL_URL" in os.environ and os.environ["SURREAL_URL"].strip():
        yield existing
        return
    yield from _start_brew_surreal()


def open_store(
    url: str, *, namespace: str = "app", database: str | None = None
) -> SurrealStore:
    return SurrealStore(
        url,
        namespace,
        database if database is not None else f"t_{uuid4().hex}",
        surreal_credentials(),
    )


def open_graph(
    url: str,
    *,
    namespace: str = "app",
    database: str | None = None,
    models: ModelStack | None = None,
    episode_window: int | None = None,
) -> Graph:
    name = database if database is not None else f"t_{uuid4().hex}"
    if episode_window is None:
        return Graph(url, namespace, name, surreal_credentials(), models=models)
    return Graph(
        url,
        namespace,
        name,
        surreal_credentials(),
        models=models,
        episode_window=episode_window,
    )


@pytest.fixture(scope="session")
def brew_surreal_url() -> Iterator[str]:
    yield from _managed_surreal_url()


@pytest.fixture
async def store(brew_surreal_url: str) -> AsyncIterator[SurrealStore]:
    impl = open_store(brew_surreal_url)
    yield impl
    await impl.aclose()


@pytest.fixture(scope="session")
def surreal_url(request: pytest.FixtureRequest) -> str:
    if not has_live_keys():
        pytest.skip("e2e needs GEMINI_API_KEY and LOGFIRE_TOKEN")
    url: str = request.getfixturevalue("brew_surreal_url")
    return url


@pytest.fixture(scope="module")
def world() -> SyntheticWorld:
    return SyntheticWorld()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def ingested(
    surreal_url: str, world: SyntheticWorld
) -> AsyncIterator[IngestedWorld]:
    graph = Graph(
        surreal_url,
        E2E_NAMESPACE,
        f"e2e_{uuid4().hex}",
        surreal_credentials(),
    )
    try:
        results: list[IngestResult] = []
        for episode in world.episodes():
            results.append(await graph.add_episode(episode.content, now=episode.now))
        yield IngestedWorld(graph=graph, world=world, results=tuple(results))
    finally:
        await graph.aclose()
