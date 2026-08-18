import ast
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from surrealdb import AsyncSurreal

from zeit import Entity, Episode, Fact, Mention, Store, SurrealStore
from zeit.store import SCHEMA

NOW = datetime(2026, 3, 1, tzinfo=UTC)
LATER = datetime(2026, 4, 1, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "zeit"
BANNED_MODULES = frozenset({"neo4j", "falkordb", "kuzu", "neptune"})


@pytest.fixture
async def store() -> AsyncIterator[SurrealStore]:
    impl = SurrealStore("mem://", "app", "memory")
    yield impl
    await impl.aclose()


def _episode() -> Episode:
    return Episode(uuid=uuid4(), content="Ada left Acme.", created_at=NOW)


def _entity(name: str = "Ada") -> Entity:
    return Entity(
        uuid=uuid4(), name=name, attributes={"role": "engineer"}, created_at=NOW
    )


def _fact(subject_id: UUID | None = None, object_id: UUID | None = None) -> Fact:
    return Fact(
        uuid=uuid4(),
        subject_id=subject_id or uuid4(),
        predicate="works_at",
        object_id=object_id or uuid4(),
        statement="Ada works at Acme.",
        valid_at=NOW,
        invalid_at=None,
        created_at=NOW,
        expired_at=None,
    )


def _mention(episode_id: UUID | None = None, entity_id: UUID | None = None) -> Mention:
    return Mention(
        uuid=uuid4(),
        episode_id=episode_id or uuid4(),
        entity_id=entity_id or uuid4(),
        surface="Ada Lovelace",
    )


def test_store_exports_from_zeit() -> None:
    assert Store.__module__ == "zeit.store"
    assert SurrealStore.__module__ == "zeit.store"


def test_surreal_store_satisfies_protocol() -> None:
    impl = SurrealStore("mem://", "app", "memory")
    assert isinstance(impl, Store)


def test_async_surreal_is_official_client() -> None:
    assert AsyncSurreal.__module__ == "surrealdb"
    source = (SRC / "store.py").read_text(encoding="utf-8")
    assert "from surrealdb import AsyncSurreal" in source


def test_no_graph_driver_abc() -> None:
    source = (SRC / "store.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert "GraphDriver" not in names


def test_src_does_not_import_other_graph_stores() -> None:
    imported: set[str] = set()
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
    assert imported.isdisjoint(BANNED_MODULES)


def test_schema_is_surrealql() -> None:
    assert "DEFINE TABLE OVERWRITE episode" in SCHEMA
    assert "DEFINE TABLE OVERWRITE entity" in SCHEMA
    assert "DEFINE TABLE OVERWRITE fact" in SCHEMA
    assert "DEFINE TABLE OVERWRITE mention" in SCHEMA
    assert "DEFINE INDEX OVERWRITE fact_statement_ft" in SCHEMA


async def test_put_get_roundtrip(store: SurrealStore) -> None:
    episode = _episode()
    ada = _entity("Ada")
    acme = Entity(uuid=uuid4(), name="Acme", created_at=NOW)
    fact = _fact(subject_id=ada.uuid, object_id=acme.uuid)
    mention = _mention(episode_id=episode.uuid, entity_id=ada.uuid)
    await store.put(episode)
    await store.put(ada, embedding=[1.0, 0.0])
    await store.put(acme, embedding=[0.0, 1.0])
    await store.put(fact, embedding=[1.0, 0.1])
    await store.put(mention)
    assert await store.get(Episode, episode.uuid) == episode
    assert await store.get(Entity, ada.uuid) == ada
    assert await store.get(Fact, fact.uuid) == fact
    assert await store.get(Mention, mention.uuid) == mention
    assert await store.get(Fact, uuid4()) is None


async def test_expire_keeps_row(store: SurrealStore) -> None:
    ada = _entity("Ada")
    acme = Entity(uuid=uuid4(), name="Acme", created_at=NOW)
    fact = _fact(subject_id=ada.uuid, object_id=acme.uuid)
    await store.put(ada)
    await store.put(acme)
    await store.put(fact)
    await store.expire(fact.uuid, invalid_at=LATER, expired_at=LATER)
    stored = await store.get(Fact, fact.uuid)
    assert stored is not None
    assert stored.invalid_at == LATER
    assert stored.expired_at == LATER
    assert stored.statement == fact.statement


async def test_search_finds_fact_by_text(store: SurrealStore) -> None:
    ada = _entity("Ada")
    acme = Entity(uuid=uuid4(), name="Acme", created_at=NOW)
    fact = _fact(subject_id=ada.uuid, object_id=acme.uuid)
    await store.put(ada)
    await store.put(acme)
    await store.put(fact, embedding=[1.0, 0.0])
    hits = await store.search("Ada", [1.0, 0.0])
    assert fact.uuid in {item.uuid for item in hits.facts}
    assert ada.uuid in {item.uuid for item in hits.entities}
