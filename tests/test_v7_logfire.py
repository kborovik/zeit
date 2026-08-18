import inspect
from pathlib import Path

import pytest

from zeit import Graph
from zeit.extract import extract_entities_agent, extract_facts_agent
from zeit.invalidate import invalidate_fact_agent
from zeit.resolve import resolve_entity_agent

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "zeit"

AGENTS = (
    extract_entities_agent,
    extract_facts_agent,
    resolve_entity_agent,
    invalidate_fact_agent,
)


def test_graph_does_not_take_logfire_token() -> None:
    params = inspect.signature(Graph.__init__).parameters
    assert "token" not in params
    assert "api_key" not in params
    assert "logfire" not in params


def test_src_does_not_own_logfire_token_or_configure() -> None:
    sources = [path.read_text(encoding="utf-8") for path in SRC.rglob("*.py")]
    joined = "\n".join(sources)
    for source in sources:
        assert "LOGFIRE_TOKEN" not in source
        assert "logfire.configure" not in source
    assert "logfire.instrument_pydantic_ai" in joined


def test_pydantic_ai_agents_are_instrumented() -> None:
    names = {agent.name for agent in AGENTS}
    assert names == {
        "zeit.extract.entities",
        "zeit.extract.facts",
        "zeit.resolve.entity",
        "zeit.invalidate.fact",
    }
    for agent in AGENTS:
        assert agent.instrument is True


def test_pydantic_ai_embedder_is_instrumented() -> None:
    source = (SRC / "embedder.py").read_text(encoding="utf-8")
    assert "instrument=True" in source


def test_graph_instruments_pydantic_ai_after_configure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import logfire

    calls: list[int] = []

    def record() -> None:
        calls.append(1)

    monkeypatch.setattr("zeit.observe._caller_configured", lambda: True)
    monkeypatch.setattr(logfire, "instrument_pydantic_ai", record)
    Graph("ws://127.0.0.1:8000/rpc", "app", "observe")
    assert calls == [1]


def test_graph_skips_instrument_until_caller_configures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import logfire

    calls: list[int] = []

    def record() -> None:
        calls.append(1)

    monkeypatch.setattr("zeit.observe._caller_configured", lambda: False)
    monkeypatch.setattr(logfire, "instrument_pydantic_ai", record)
    Graph("ws://127.0.0.1:8000/rpc", "app", "observe-skip")
    assert calls == []
