from dataclasses import fields
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from zeit import Entity, Episode, Fact, IngestResult, Mention, SearchHits

NOW = datetime(2026, 3, 1, tzinfo=UTC)

CLOSED = {
    Episode: ("uuid", "content", "created_at"),
    Entity: ("uuid", "name", "attributes", "created_at"),
    Fact: (
        "uuid",
        "subject_id",
        "predicate",
        "object_id",
        "statement",
        "valid_at",
        "invalid_at",
        "created_at",
        "expired_at",
    ),
    Mention: ("uuid", "episode_id", "entity_id", "surface"),
    IngestResult: ("episode", "entities", "facts", "mentions"),
    SearchHits: ("facts", "entities"),
}


def _episode() -> Episode:
    return Episode(uuid=uuid4(), content="Ada left Acme.", created_at=NOW)


def _entity() -> Entity:
    return Entity(uuid=uuid4(), name="Ada", created_at=NOW)


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


def test_types_export_from_zeit() -> None:
    assert Episode.__module__ == "zeit.types"
    assert Entity.__module__ == "zeit.types"
    assert Fact.__module__ == "zeit.types"
    assert Mention.__module__ == "zeit.types"
    assert IngestResult.__module__ == "zeit.types"
    assert SearchHits.__module__ == "zeit.types"


def test_field_sets_are_closed() -> None:
    for cls, names in CLOSED.items():
        assert tuple(item.name for item in fields(cls)) == names


def test_persistable_types_have_no_tenant_field() -> None:
    for cls in (Episode, Entity, Fact, Mention):
        assert "tenant" not in {item.name for item in fields(cls)}


def _new(cls: Any, **values: object) -> object:
    return cls(**values)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(TypeError):
        _new(Episode, uuid=uuid4(), content="x", created_at=NOW, tenant="app")
    with pytest.raises(TypeError):
        _new(Entity, uuid=uuid4(), name="Ada", created_at=NOW, extra="no")
    with pytest.raises(TypeError):
        _new(
            Fact,
            uuid=uuid4(),
            subject_id=uuid4(),
            predicate="works_at",
            object_id=uuid4(),
            statement="Ada works at Acme.",
            valid_at=NOW,
            invalid_at=None,
            created_at=NOW,
            expired_at=None,
            tenant="app",
        )
    with pytest.raises(TypeError):
        _new(
            Mention,
            uuid=uuid4(),
            episode_id=uuid4(),
            entity_id=uuid4(),
            surface="Ada",
            tenant="app",
        )


def test_entity_attributes_is_untyped_dict() -> None:
    entity = Entity(
        uuid=uuid4(),
        name="Ada",
        attributes={"role": "engineer", "headcount": 1},
        created_at=NOW,
    )
    assert entity.attributes == {"role": "engineer", "headcount": 1}
    assert type(entity.attributes) is dict
    defaulted = Entity(uuid=uuid4(), name="Acme", created_at=NOW)
    assert defaulted.attributes == {}


def test_types_are_final() -> None:
    for cls in (Episode, Entity, Fact, Mention, IngestResult, SearchHits):
        assert getattr(cls, "__final__", False) is True


def test_ingest_and_search_value_objects() -> None:
    episode = _episode()
    entity = _entity()
    fact = _fact(subject_id=entity.uuid)
    mention = _mention(episode_id=episode.uuid, entity_id=entity.uuid)
    ingested = IngestResult(
        episode=episode,
        entities=(entity,),
        facts=(fact,),
        mentions=(mention,),
    )
    hits = SearchHits(facts=(fact,), entities=(entity,))
    assert ingested.episode is episode
    assert ingested.entities == (entity,)
    assert hits.facts == (fact,)
    assert hits.entities == (entity,)
    assert IngestResult() == IngestResult()
    assert SearchHits() == SearchHits()
