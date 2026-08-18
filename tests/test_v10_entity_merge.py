from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings

from zeit import BoundEntity, Entity, Resolution, SurrealStore, resolve
from zeit.extract import ExtractedEntity

NOW = datetime(2026, 3, 1, tzinfo=UTC)


@pytest.fixture
async def store() -> AsyncIterator[SurrealStore]:
    impl = SurrealStore("mem://", "app", "memory")
    yield impl
    await impl.aclose()


def _entity(name: str = "Ada") -> Entity:
    return Entity(
        uuid=uuid4(),
        name=name,
        attributes={"role": "person"},
        created_at=NOW,
    )


class _Boom(TestModel):
    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        raise AssertionError("resolve must not call the model")


async def test_exact_name_reuses_existing_uuid(store: SurrealStore) -> None:
    ada = _entity("Ada")
    await store.put(ada)
    result = await resolve(
        (ExtractedEntity(name="Ada", attributes={"role": "engineer"}),),
        store,
        model=_Boom(),
        now=NOW,
    )
    assert result.entities == (ada,)
    assert result.bindings == (BoundEntity(surface="Ada", entity=ada),)
    assert result.entities[0].attributes == {"role": "person"}


async def test_alias_surface_merges_onto_existing_uuid(store: SurrealStore) -> None:
    ada = _entity("Ada")
    await store.put(ada)
    result = await resolve(
        (ExtractedEntity(name="Ada Lovelace"),),
        store,
        model=TestModel(custom_output_args={"existing_name": "Ada"}),
        now=NOW,
    )
    assert result.entities == (ada,)
    assert result.bindings[0].surface == "Ada Lovelace"
    assert result.bindings[0].entity.uuid == ada.uuid


async def test_two_new_surfaces_share_one_uuid(store: SurrealStore) -> None:
    result = await resolve(
        (
            ExtractedEntity(name="Ada", attributes={"role": "person"}),
            ExtractedEntity(name="Ada Lovelace"),
        ),
        store,
        model=TestModel(custom_output_args={"existing_name": "Ada"}),
        now=NOW,
    )
    assert len(result.entities) == 1
    entity = result.entities[0]
    assert entity.name == "Ada"
    assert entity.attributes == {"role": "person"}
    assert entity.created_at == NOW
    assert [item.surface for item in result.bindings] == ["Ada", "Ada Lovelace"]
    assert {item.entity.uuid for item in result.bindings} == {entity.uuid}


async def test_distinct_surfaces_keep_distinct_uuids(store: SurrealStore) -> None:
    result = await resolve(
        (ExtractedEntity(name="Ada"), ExtractedEntity(name="Acme")),
        store,
        model=TestModel(custom_output_args={"existing_name": None}),
        now=NOW,
    )
    assert len(result.entities) == 2
    assert result.entities[0].name == "Ada"
    assert result.entities[1].name == "Acme"
    assert result.entities[0].uuid != result.entities[1].uuid
    assert [item.entity.uuid for item in result.bindings] == [
        result.entities[0].uuid,
        result.entities[1].uuid,
    ]


async def test_same_surface_twice_reuses_one_uuid(store: SurrealStore) -> None:
    result = await resolve(
        (
            ExtractedEntity(name="Ada", attributes={"role": "person"}),
            ExtractedEntity(name="Ada", attributes={"role": "ignored"}),
        ),
        store,
        model=_Boom(),
        now=NOW,
    )
    assert len(result.entities) == 1
    assert result.bindings[0].entity is result.bindings[1].entity
    assert result.entities[0].attributes == {"role": "person"}


async def test_empty_extract_skips_model(store: SurrealStore) -> None:
    assert await resolve((), store, model=_Boom(), now=NOW) == Resolution()


async def test_other_database_entities_are_not_candidates() -> None:
    ada = _entity("Ada")
    memory = SurrealStore("mem://", "app", "memory")
    other = SurrealStore("mem://", "app", "other")
    try:
        await other.put(ada)
        result = await resolve(
            (ExtractedEntity(name="Ada"),),
            memory,
            model=_Boom(),
            now=NOW,
        )
        assert len(result.entities) == 1
        assert result.entities[0].uuid != ada.uuid
        assert result.entities[0].name == "Ada"
    finally:
        await memory.aclose()
        await other.aclose()


async def test_resolve_includes_prior_in_prompt(store: SurrealStore) -> None:
    await store.put(_entity("Ada"))
    with capture_run_messages() as messages:
        await resolve(
            (ExtractedEntity(name="Ada Lovelace"),),
            store,
            model=TestModel(custom_output_args={"existing_name": "Ada"}),
            prior=("Ada works at Acme.",),
            now=NOW,
        )
    requests = [item for item in messages if isinstance(item, ModelRequest)]
    assert requests
    part = requests[0].parts[0]
    assert isinstance(part, UserPromptPart)
    assert isinstance(part.content, str)
    assert "Ada Lovelace" in part.content
    assert "Ada works at Acme." in part.content
