import inspect
from pathlib import Path

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
    for path in SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "LOGFIRE_TOKEN" not in source
        assert "logfire.configure" not in source
        assert "import logfire" not in source
        assert "from logfire" not in source


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
