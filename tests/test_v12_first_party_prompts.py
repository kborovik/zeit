from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel

from zeit import Entity, SurrealStore
from zeit.extract import (
    ENTITY_INSTRUCTIONS,
    FACT_INSTRUCTIONS,
    ExtractedEntities,
    ExtractedEntity,
    ExtractedFact,
    ExtractedFacts,
    extract_entities,
    extract_facts,
)
from zeit.resolve import RESOLVE_INSTRUCTIONS, EntityMatch, resolve
from zeit.types import Fact

NOW = datetime(2026, 3, 1, tzinfo=UTC)


def test_output_models_are_first_party_pydantic() -> None:
    for cls in (ExtractedEntity, ExtractedFact, ExtractedEntities, ExtractedFacts):
        assert cls.__module__ == "zeit.extract"
        assert issubclass(cls, BaseModel)
    assert EntityMatch.__module__ == "zeit.resolve"
    assert issubclass(EntityMatch, BaseModel)
    assert ExtractedEntity is not Entity
    assert ExtractedFact is not Fact
    assert EntityMatch is not Entity


def test_instructions_are_first_party() -> None:
    assert "bi-temporal knowledge graph" in ENTITY_INSTRUCTIONS
    assert "Do not invent entities" in ENTITY_INSTRUCTIONS
    assert "expired, not overwritten" in FACT_INSTRUCTIONS
    assert "subject and object must be entity names" in FACT_INSTRUCTIONS
    assert "same real-world entity" in RESOLVE_INSTRUCTIONS
    assert "Return no existing_name" in RESOLVE_INSTRUCTIONS
    assert "graphiti" not in ENTITY_INSTRUCTIONS.lower()
    assert "graphiti" not in FACT_INSTRUCTIONS.lower()
    assert "graphiti" not in RESOLVE_INSTRUCTIONS.lower()


async def test_entity_agent_sends_first_party_instructions() -> None:
    with capture_run_messages() as messages:
        await extract_entities(
            "Ada left Acme.",
            model=TestModel(custom_output_args={"entities": [{"name": "Ada"}]}),
            prior=("Ada works at Acme.",),
        )
    requests = [item for item in messages if isinstance(item, ModelRequest)]
    assert requests
    assert requests[0].instructions == ENTITY_INSTRUCTIONS
    part = requests[0].parts[0]
    assert isinstance(part, UserPromptPart)
    assert isinstance(part.content, str)
    assert "Ada left Acme." in part.content
    assert "Ada works at Acme." in part.content


async def test_fact_agent_sends_first_party_instructions() -> None:
    entities = (
        ExtractedEntity(name="Ada"),
        ExtractedEntity(name="Acme"),
    )
    with capture_run_messages() as messages:
        facts = await extract_facts(
            "Ada left Acme in March 2026.",
            entities,
            model=TestModel(
                custom_output_args={
                    "facts": [
                        {
                            "subject": "Ada",
                            "predicate": "left",
                            "object": "Acme",
                            "statement": "Ada left Acme.",
                            "valid_at": "2026-03-01T00:00:00Z",
                        }
                    ]
                }
            ),
        )
    requests = [item for item in messages if isinstance(item, ModelRequest)]
    assert requests
    assert requests[0].instructions == FACT_INSTRUCTIONS
    part = requests[0].parts[0]
    assert isinstance(part, UserPromptPart)
    assert isinstance(part.content, str)
    assert "Ada" in part.content
    assert "Acme" in part.content
    assert facts == (
        ExtractedFact(
            subject="Ada",
            predicate="left",
            object="Acme",
            statement="Ada left Acme.",
            valid_at=NOW,
        ),
    )


async def test_resolve_agent_sends_first_party_instructions() -> None:
    store = SurrealStore("mem://", "app", "memory")
    try:
        await store.put(
            Entity(uuid=uuid4(), name="Ada", created_at=NOW),
        )
        with capture_run_messages() as messages:
            await resolve(
                (ExtractedEntity(name="Ada Lovelace"),),
                store,
                model=TestModel(custom_output_args={"existing_name": "Ada"}),
                now=NOW,
            )
    finally:
        await store.aclose()
    requests = [item for item in messages if isinstance(item, ModelRequest)]
    assert requests
    assert requests[0].instructions == RESOLVE_INSTRUCTIONS
    part = requests[0].parts[0]
    assert isinstance(part, UserPromptPart)
    assert isinstance(part.content, str)
    assert "Ada Lovelace" in part.content
    assert "Ada" in part.content
