"""Invalidate existing facts that new claims contradict."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, format_as_xml
from pydantic_ai.models import Model

from .extract import ExtractedFact
from .resolve import Resolution
from .store import SurrealStore
from .types import Entity, Fact

INVALIDATE_INSTRUCTIONS = """\
You decide which existing facts a new claim contradicts.
An existing fact is contradicted when it cannot still be true if the new claim is true.
Return the statement of each contradicted existing fact exactly.
Do not return a fact that can still be true alongside the new claims.
Do not invent statements.
A new workplace or status for the same entity usually contradicts the previous one.
A new fact about a different entity does not contradict the old one."""


class Contradiction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statements: list[str] = Field(default_factory=list)


invalidate_fact_agent: Agent[None, Contradiction] = Agent(
    name="zeit.invalidate.fact",
    output_type=Contradiction,
    instructions=INVALIDATE_INSTRUCTIONS,
)
invalidate_fact_agent.instrument = True


def _bound(resolution: Resolution) -> dict[str, Entity]:
    by_name = {entity.name: entity for entity in resolution.entities}
    for item in resolution.bindings:
        by_name[item.surface] = item.entity
    return by_name


def _entity_ids(
    extracted: Sequence[ExtractedFact], bound: dict[str, Entity]
) -> list[UUID]:
    ids: list[UUID] = []
    seen: set[UUID] = set()
    for fact in extracted:
        for name in (fact.subject, fact.object):
            entity = bound.get(name)
            if entity is not None and entity.uuid not in seen:
                seen.add(entity.uuid)
                ids.append(entity.uuid)
    return ids


def _xml(extracted: Sequence[ExtractedFact], existing: Sequence[Fact]) -> str:
    return format_as_xml(
        {
            "new": [
                {
                    "subject": fact.subject,
                    "predicate": fact.predicate,
                    "object": fact.object,
                    "statement": fact.statement,
                    **(
                        {"valid_at": fact.valid_at.isoformat()}
                        if fact.valid_at is not None
                        else {}
                    ),
                }
                for fact in extracted
            ],
            "existing": [
                {
                    "statement": fact.statement,
                    "predicate": fact.predicate,
                    "valid_at": fact.valid_at.isoformat(),
                }
                for fact in existing
            ],
        },
        root_tag="input",
    )


def _world_time(extracted: Sequence[ExtractedFact], now: datetime) -> datetime:
    times = [fact.valid_at for fact in extracted if fact.valid_at is not None]
    return min(times) if times else now


def _expired(fact: Fact, *, invalid_at: datetime, expired_at: datetime) -> Fact:
    return Fact(
        uuid=fact.uuid,
        subject_id=fact.subject_id,
        predicate=fact.predicate,
        object_id=fact.object_id,
        statement=fact.statement,
        valid_at=fact.valid_at,
        invalid_at=invalid_at,
        created_at=fact.created_at,
        expired_at=expired_at,
    )


async def invalidate(
    extracted: Sequence[ExtractedFact],
    resolution: Resolution,
    store: SurrealStore,
    *,
    model: str | Model,
    now: datetime | None = None,
) -> tuple[Fact, ...]:
    if not extracted:
        return ()
    stamp = now if now is not None else datetime.now(UTC)
    ids = _entity_ids(extracted, _bound(resolution))
    if not ids:
        return ()
    existing = await store.open_facts(ids)
    if not existing:
        return ()
    result = await invalidate_fact_agent.run(_xml(extracted, existing), model=model)
    wanted = set(result.output.statements)
    invalid_at = _world_time(extracted, stamp)
    expired: list[Fact] = []
    for fact in existing:
        if fact.statement not in wanted:
            continue
        await store.expire(fact.uuid, invalid_at=invalid_at, expired_at=stamp)
        expired.append(_expired(fact, invalid_at=invalid_at, expired_at=stamp))
    return tuple(expired)
