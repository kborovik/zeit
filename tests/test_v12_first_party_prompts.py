from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel

from zeit import BoundEntity, Entity, Fact, Resolution, SurrealStore
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
from zeit.invalidate import INVALIDATE_INSTRUCTIONS, Contradiction, invalidate
from zeit.resolve import RESOLVE_INSTRUCTIONS, EntityMatch, resolve

NOW = datetime(2026, 3, 1, tzinfo=UTC)


def test_output_models_are_first_party_pydantic() -> None:
    for cls in (ExtractedEntity, ExtractedFact, ExtractedEntities, ExtractedFacts):
        assert cls.__module__ == "zeit.extract"
        assert issubclass(cls, BaseModel)
    assert EntityMatch.__module__ == "zeit.resolve"
    assert issubclass(EntityMatch, BaseModel)
    assert Contradiction.__module__ == "zeit.invalidate"
    assert issubclass(Contradiction, BaseModel)
    assert ExtractedEntity is not Entity
    assert ExtractedFact is not Fact
    assert EntityMatch is not Entity
    assert Contradiction is not Fact


def test_instructions_are_first_party() -> None:
    assert "bi-temporal knowledge graph" in ENTITY_INSTRUCTIONS
    assert "Do not invent entities" in ENTITY_INSTRUCTIONS
    assert "expired, not overwritten" in FACT_INSTRUCTIONS
    assert "subject and object must be entity names" in FACT_INSTRUCTIONS
    assert "same real-world entity" in RESOLVE_INSTRUCTIONS
    assert "Return no existing_name" in RESOLVE_INSTRUCTIONS
    assert "existing facts a new claim contradicts" in INVALIDATE_INSTRUCTIONS
    assert "Return the statement" in INVALIDATE_INSTRUCTIONS
    assert "graphiti" not in ENTITY_INSTRUCTIONS.lower()
    assert "graphiti" not in FACT_INSTRUCTIONS.lower()
    assert "graphiti" not in RESOLVE_INSTRUCTIONS.lower()
    assert "graphiti" not in INVALIDATE_INSTRUCTIONS.lower()


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


async def test_invalidate_agent_sends_first_party_instructions() -> None:
    ada = Entity(uuid=uuid4(), name="Ada", created_at=NOW)
    acme = Entity(uuid=uuid4(), name="Acme", created_at=NOW)
    birch = Entity(uuid=uuid4(), name="Birch", created_at=NOW)
    old = Fact(
        uuid=uuid4(),
        subject_id=ada.uuid,
        predicate="works_at",
        object_id=acme.uuid,
        statement="Ada works at Acme.",
        valid_at=NOW,
        invalid_at=None,
        created_at=NOW,
        expired_at=None,
    )
    store = SurrealStore("mem://", "app", "memory")
    try:
        await store.put(ada)
        await store.put(acme)
        await store.put(birch)
        await store.put(old)
        with capture_run_messages() as messages:
            await invalidate(
                (
                    ExtractedFact(
                        subject="Ada",
                        predicate="works_at",
                        object="Birch",
                        statement="Ada works at Birch.",
                    ),
                ),
                Resolution(
                    entities=(ada, birch),
                    bindings=(
                        BoundEntity(surface="Ada", entity=ada),
                        BoundEntity(surface="Birch", entity=birch),
                    ),
                ),
                store,
                model=TestModel(custom_output_args={"statements": [old.statement]}),
                now=NOW,
            )
    finally:
        await store.aclose()
    requests = [item for item in messages if isinstance(item, ModelRequest)]
    assert requests
    assert requests[0].instructions == INVALIDATE_INSTRUCTIONS
    part = requests[0].parts[0]
    assert isinstance(part, UserPromptPart)
    assert isinstance(part.content, str)
    assert "Ada works at Acme." in part.content
    assert "Ada works at Birch." in part.content
