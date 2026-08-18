"""Resolve extracted surface forms onto existing graph entities."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import final
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent, format_as_xml
from pydantic_ai.models import Model

from .extract import ExtractedEntity
from .store import SurrealStore
from .types import Entity

RESOLVE_INSTRUCTIONS = """\
You decide if an extracted surface form is the same real-world entity as a candidate.
Candidates are stored in this database or already resolved in this episode.
Return existing_name when the surface is the same entity as that candidate.
Use the candidate name exactly.
Return no existing_name when the surface is a new, distinct entity.
Do not merge different people, organizations, or places just because names share a word.
Use attributes and prior episode text only as hints."""


class EntityMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    existing_name: str | None = None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class BoundEntity:
    surface: str
    entity: Entity


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Resolution:
    entities: tuple[Entity, ...] = ()
    bindings: tuple[BoundEntity, ...] = ()


resolve_entity_agent: Agent[None, EntityMatch] = Agent(
    name="zeit.resolve.entity",
    output_type=EntityMatch,
    instructions=RESOLVE_INSTRUCTIONS,
)
resolve_entity_agent.instrument = True


def _new_entity(extracted: ExtractedEntity, now: datetime) -> Entity:
    return Entity(
        uuid=uuid4(),
        name=extracted.name,
        attributes=dict(extracted.attributes),
        created_at=now,
    )


def _resolve_xml(
    extracted: ExtractedEntity,
    candidates: Sequence[Entity],
    prior: Sequence[str],
) -> str:
    return format_as_xml(
        {
            "prior": list(prior),
            "extracted": {
                "name": extracted.name,
                "attributes": extracted.attributes,
            },
            "candidates": [
                {"name": entity.name, "attributes": entity.attributes}
                for entity in candidates
            ],
        },
        root_tag="input",
    )


def _candidate_queries(name: str) -> tuple[str, ...]:
    seen: set[str] = set()
    queries: list[str] = []
    for token in (name, *name.split()):
        if token and token not in seen:
            seen.add(token)
            queries.append(token)
    return tuple(queries)


async def _candidates(
    store: SurrealStore,
    name: str,
    known: Sequence[Entity],
) -> list[Entity]:
    found: dict[UUID, Entity] = {entity.uuid: entity for entity in known}
    for query in _candidate_queries(name):
        for entity in await store.entities_named(query):
            found[entity.uuid] = entity
        for entity in (await store.search(query, [])).entities:
            found[entity.uuid] = entity
    return list(found.values())


def _named(candidates: Sequence[Entity], name: str) -> Entity | None:
    for entity in candidates:
        if entity.name == name:
            return entity
    return None


async def _match(
    extracted: ExtractedEntity,
    candidates: Sequence[Entity],
    *,
    model: str | Model,
    prior: Sequence[str],
) -> Entity | None:
    result = await resolve_entity_agent.run(
        _resolve_xml(extracted, candidates, prior),
        model=model,
    )
    name = result.output.existing_name
    if name is None:
        return None
    return _named(candidates, name)


async def resolve(
    extracted: Sequence[ExtractedEntity],
    store: SurrealStore,
    *,
    model: str | Model,
    prior: Sequence[str] = (),
    now: datetime | None = None,
) -> Resolution:
    if not extracted:
        return Resolution()
    stamp = now if now is not None else datetime.now(UTC)
    by_surface: dict[str, Entity] = {}
    unique: list[Entity] = []
    seen: set[UUID] = set()

    for item in extracted:
        if item.name in by_surface:
            continue
        existing = await store.entities_named(item.name)
        if existing:
            entity = existing[0]
            by_surface[item.name] = entity
            if entity.uuid not in seen:
                seen.add(entity.uuid)
                unique.append(entity)
            continue
        candidates = await _candidates(store, item.name, unique)
        matched = None
        if candidates:
            matched = await _match(item, candidates, model=model, prior=prior)
        entity = matched if matched is not None else _new_entity(item, stamp)
        by_surface[item.name] = entity
        if entity.uuid not in seen:
            seen.add(entity.uuid)
            unique.append(entity)

    bindings = tuple(
        BoundEntity(surface=item.name, entity=by_surface[item.name])
        for item in extracted
    )
    return Resolution(entities=tuple(unique), bindings=bindings)
