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

from zeit import BoundEntity, Entity, Fact, Resolution, SurrealStore, invalidate
from zeit.extract import ExtractedFact

JAN = datetime(2026, 1, 1, tzinfo=UTC)
MARCH = datetime(2026, 3, 1, tzinfo=UTC)
APRIL = datetime(2026, 4, 1, tzinfo=UTC)


@pytest.fixture
async def store() -> AsyncIterator[SurrealStore]:
    impl = SurrealStore("mem://", "app", "memory")
    yield impl
    await impl.aclose()


def _entity(name: str) -> Entity:
    return Entity(uuid=uuid4(), name=name, created_at=JAN)


def _fact(
    subject: Entity,
    obj: Entity,
    *,
    statement: str = "Ada works at Acme.",
    predicate: str = "works_at",
    valid_at: datetime = JAN,
    created_at: datetime = JAN,
    invalid_at: datetime | None = None,
    expired_at: datetime | None = None,
) -> Fact:
    return Fact(
        uuid=uuid4(),
        subject_id=subject.uuid,
        predicate=predicate,
        object_id=obj.uuid,
        statement=statement,
        valid_at=valid_at,
        invalid_at=invalid_at,
        created_at=created_at,
        expired_at=expired_at,
    )


def _resolution(*entities: Entity) -> Resolution:
    bindings = tuple(
        BoundEntity(surface=entity.name, entity=entity) for entity in entities
    )
    return Resolution(entities=entities, bindings=bindings)


def _extracted(
    *,
    subject: str = "Ada",
    predicate: str = "works_at",
    obj: str = "Birch",
    statement: str = "Ada works at Birch.",
    valid_at: datetime | None = MARCH,
) -> ExtractedFact:
    return ExtractedFact(
        subject=subject,
        predicate=predicate,
        object=obj,
        statement=statement,
        valid_at=valid_at,
    )


class _Boom(TestModel):
    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        raise AssertionError("invalidate must not call the model")


async def _seed(store: SurrealStore, *records: Entity | Fact) -> None:
    for record in records:
        await store.put(record)


async def test_contradiction_expires_fact_without_drop(store: SurrealStore) -> None:
    ada = _entity("Ada")
    acme = _entity("Acme")
    birch = _entity("Birch")
    old = _fact(ada, acme)
    await _seed(store, ada, acme, birch, old)
    expired = await invalidate(
        (_extracted(),),
        _resolution(ada, birch),
        store,
        model=TestModel(custom_output_args={"statements": [old.statement]}),
        now=APRIL,
    )
    assert len(expired) == 1
    assert expired[0].uuid == old.uuid
    assert expired[0].invalid_at == MARCH
    assert expired[0].expired_at == APRIL
    assert expired[0].valid_at == JAN
    assert expired[0].created_at == JAN
    stored = await store.get(Fact, old.uuid)
    assert stored is not None
    assert stored == expired[0]
    assert stored.statement == old.statement


async def test_missing_valid_at_uses_txn_now_for_both_clocks(
    store: SurrealStore,
) -> None:
    ada = _entity("Ada")
    acme = _entity("Acme")
    birch = _entity("Birch")
    old = _fact(ada, acme)
    await _seed(store, ada, acme, birch, old)
    expired = await invalidate(
        (_extracted(valid_at=None),),
        _resolution(ada, birch),
        store,
        model=TestModel(custom_output_args={"statements": [old.statement]}),
        now=APRIL,
    )
    assert expired[0].invalid_at == APRIL
    assert expired[0].expired_at == APRIL


async def test_non_contradiction_leaves_fact_open(store: SurrealStore) -> None:
    ada = _entity("Ada")
    acme = _entity("Acme")
    old = _fact(ada, acme)
    await _seed(store, ada, acme, old)
    expired = await invalidate(
        (
            ExtractedFact(
                subject="Ada",
                predicate="founded",
                object="Acme",
                statement="Ada founded Acme.",
            ),
        ),
        _resolution(ada, acme),
        store,
        model=TestModel(custom_output_args={"statements": []}),
        now=APRIL,
    )
    assert expired == ()
    stored = await store.get(Fact, old.uuid)
    assert stored == old
    assert stored is not None
    assert stored.invalid_at is None
    assert stored.expired_at is None


async def test_empty_extract_skips_model(store: SurrealStore) -> None:
    assert await invalidate((), Resolution(), store, model=_Boom(), now=APRIL) == ()


async def test_no_open_facts_skips_model(store: SurrealStore) -> None:
    ada = _entity("Ada")
    birch = _entity("Birch")
    await _seed(store, ada, birch)
    assert (
        await invalidate(
            (_extracted(),),
            _resolution(ada, birch),
            store,
            model=_Boom(),
            now=APRIL,
        )
        == ()
    )


async def test_already_expired_fact_is_not_a_candidate(store: SurrealStore) -> None:
    ada = _entity("Ada")
    acme = _entity("Acme")
    birch = _entity("Birch")
    old = _fact(ada, acme, invalid_at=MARCH, expired_at=MARCH)
    await _seed(store, ada, acme, birch, old)
    assert (
        await invalidate(
            (_extracted(),),
            _resolution(ada, birch),
            store,
            model=_Boom(),
            now=APRIL,
        )
        == ()
    )
    stored = await store.get(Fact, old.uuid)
    assert stored == old


async def test_other_database_facts_are_not_expired() -> None:
    ada = _entity("Ada")
    acme = _entity("Acme")
    birch = _entity("Birch")
    old = _fact(ada, acme)
    memory = SurrealStore("mem://", "app", "memory")
    other = SurrealStore("mem://", "app", "other")
    try:
        await _seed(other, ada, acme, birch, old)
        expired = await invalidate(
            (_extracted(),),
            _resolution(ada, birch),
            memory,
            model=_Boom(),
            now=APRIL,
        )
        assert expired == ()
        assert await other.get(Fact, old.uuid) == old
    finally:
        await memory.aclose()
        await other.aclose()


async def test_unrelated_entity_facts_are_not_candidates(store: SurrealStore) -> None:
    ada = _entity("Ada")
    acme = _entity("Acme")
    birch = _entity("Birch")
    bob = _entity("Bob")
    old = _fact(bob, acme, statement="Bob works at Acme.")
    await _seed(store, ada, acme, birch, bob, old)
    assert (
        await invalidate(
            (_extracted(),),
            _resolution(ada, birch),
            store,
            model=_Boom(),
            now=APRIL,
        )
        == ()
    )
    stored = await store.get(Fact, old.uuid)
    assert stored == old


async def test_invalidate_includes_statements_in_prompt(store: SurrealStore) -> None:
    ada = _entity("Ada")
    acme = _entity("Acme")
    birch = _entity("Birch")
    old = _fact(ada, acme)
    await _seed(store, ada, acme, birch, old)
    with capture_run_messages() as messages:
        await invalidate(
            (_extracted(),),
            _resolution(ada, birch),
            store,
            model=TestModel(custom_output_args={"statements": [old.statement]}),
            now=APRIL,
        )
    requests = [item for item in messages if isinstance(item, ModelRequest)]
    assert requests
    part = requests[0].parts[0]
    assert isinstance(part, UserPromptPart)
    assert isinstance(part.content, str)
    assert "Ada works at Acme." in part.content
    assert "Ada works at Birch." in part.content
