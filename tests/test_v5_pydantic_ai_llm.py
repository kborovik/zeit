import ast
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings

from zeit.extract import (
    ExtractedEntity,
    extract,
    extract_entities,
    extract_entities_agent,
    extract_facts,
    extract_facts_agent,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "zeit"
BANNED_LLM = frozenset(
    {"openai", "anthropic", "litellm", "langchain", "google.generativeai"}
)


def test_extract_agents_are_pydantic_ai_agents() -> None:
    assert isinstance(extract_entities_agent, Agent)
    assert isinstance(extract_facts_agent, Agent)
    source = (SRC / "extract.py").read_text(encoding="utf-8")
    assert "from pydantic_ai import Agent" in source


def test_src_does_not_import_other_llm_clients() -> None:
    imported: set[str] = set()
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    assert imported.isdisjoint(BANNED_LLM)


async def test_extract_entities_runs_through_agent() -> None:
    entities = await extract_entities(
        "Ada left Acme.",
        model=TestModel(
            custom_output_args={
                "entities": [
                    {"name": "Ada", "attributes": {"role": "person"}},
                    {"name": "Acme", "attributes": {"role": "org"}},
                ]
            }
        ),
    )
    assert entities == (
        ExtractedEntity(name="Ada", attributes={"role": "person"}),
        ExtractedEntity(name="Acme", attributes={"role": "org"}),
    )


async def test_extract_facts_skips_llm_when_no_entities() -> None:
    facts = await extract_facts("Ada left Acme.", entities=(), model=TestModel())
    assert facts == ()


async def test_extract_runs_both_agents() -> None:
    class _Counting(TestModel):
        def __init__(self) -> None:
            super().__init__(
                custom_output_args={"entities": [{"name": "Ada"}, {"name": "Acme"}]}
            )
            self.calls = 0

        async def request(
            self,
            messages: list[ModelMessage],
            model_settings: ModelSettings | None,
            model_request_parameters: ModelRequestParameters,
        ) -> ModelResponse:
            self.calls += 1
            if self.calls == 1:
                self.custom_output_args = {
                    "entities": [{"name": "Ada"}, {"name": "Acme"}]
                }
            else:
                self.custom_output_args = {
                    "facts": [
                        {
                            "subject": "Ada",
                            "predicate": "left",
                            "object": "Acme",
                            "statement": "Ada left Acme.",
                        }
                    ]
                }
            return await super().request(
                messages, model_settings, model_request_parameters
            )

    model = _Counting()
    result = await extract("Ada left Acme.", model=model)
    assert model.calls == 2
    assert [entity.name for entity in result.entities] == ["Ada", "Acme"]
    assert result.facts[0].statement == "Ada left Acme."
