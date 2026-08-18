from dataclasses import fields
from datetime import UTC, datetime
from uuid import uuid4

from conftest import open_store
from zeit import Entity, Episode, Fact, Mention, SurrealStore
from zeit.store import SCHEMA

NOW = datetime(2026, 3, 1, tzinfo=UTC)


def test_persistable_types_have_no_tenant_field() -> None:
    for cls in (Episode, Entity, Fact, Mention):
        assert "tenant" not in {item.name for item in fields(cls)}


def test_schema_has_no_tenant_field() -> None:
    assert "tenant" not in SCHEMA


def test_store_binds_one_namespace_and_database() -> None:
    impl = SurrealStore("ws://127.0.0.1:8000/rpc", "app", "memory")
    assert impl.namespace == "app"
    assert impl.database == "memory"


async def test_other_database_is_invisible(brew_surreal_url: str) -> None:
    fact = Fact(
        uuid=uuid4(),
        subject_id=uuid4(),
        predicate="works_at",
        object_id=uuid4(),
        statement="Ada works at Acme.",
        valid_at=NOW,
        invalid_at=None,
        created_at=NOW,
        expired_at=None,
    )
    ada = Entity(uuid=fact.subject_id, name="Ada", created_at=NOW)
    acme = Entity(uuid=fact.object_id, name="Acme", created_at=NOW)
    memory = open_store(brew_surreal_url)
    other = open_store(brew_surreal_url)
    try:
        await memory.put(ada)
        await memory.put(acme)
        await memory.put(fact)
        assert await memory.get(Fact, fact.uuid) == fact
        assert await other.get(Fact, fact.uuid) is None
        assert await other.get(Entity, ada.uuid) is None
    finally:
        await memory.aclose()
        await other.aclose()
