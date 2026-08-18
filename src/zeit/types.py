"""Closed graph types. Field sets are fixed; callers do not subclass."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import final
from uuid import UUID


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Episode:
    uuid: UUID
    content: str
    created_at: datetime


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Entity:
    uuid: UUID
    name: str
    attributes: dict[str, object] = field(default_factory=dict)
    created_at: datetime


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Fact:
    uuid: UUID
    subject_id: UUID
    predicate: str
    object_id: UUID
    statement: str
    valid_at: datetime
    invalid_at: datetime | None
    created_at: datetime
    expired_at: datetime | None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Mention:
    uuid: UUID
    episode_id: UUID
    entity_id: UUID
    surface: str


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class IngestResult:
    episode: Episode | None = None
    entities: tuple[Entity, ...] = ()
    facts: tuple[Fact, ...] = ()
    mentions: tuple[Mention, ...] = ()


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class SearchHits:
    facts: tuple[Fact, ...] = ()
    entities: tuple[Entity, ...] = ()
