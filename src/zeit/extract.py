"""First-party extract prompts and PydanticAI agents."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import final

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, format_as_xml
from pydantic_ai.models import Model

ENTITY_INSTRUCTIONS = """\
You extract named entities from one episode of a bi-temporal knowledge graph.
An episode is a note, chat turn, or event.
Return every person, organization, place, or thing the episode names.
Use the name as it should appear on the entity later.
Put optional type or role hints in attributes.
Use prior episodes only to resolve pronouns and short names.
Do not invent entities the episode does not mention."""

FACT_INSTRUCTIONS = """\
You extract facts from one episode of a bi-temporal knowledge graph.
A fact is a subject-predicate-object claim that can later be expired, not overwritten.
subject and object must be entity names from the provided list.
statement is one standalone English sentence for the claim.
Set valid_at only when the episode states when the claim became true.
Extract the new claim even when it contradicts a prior episode.
Do not extract opinions, questions, or future plans as facts."""


class ExtractedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    attributes: dict[str, object] = Field(default_factory=dict)


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str
    predicate: str
    object: str
    statement: str
    valid_at: datetime | None = None


class ExtractedEntities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: list[ExtractedEntity] = Field(default_factory=list)


class ExtractedFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[ExtractedFact] = Field(default_factory=list)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Extraction:
    entities: tuple[ExtractedEntity, ...] = ()
    facts: tuple[ExtractedFact, ...] = ()


extract_entities_agent: Agent[None, ExtractedEntities] = Agent(
    name="zeit.extract.entities",
    output_type=ExtractedEntities,
    instructions=ENTITY_INSTRUCTIONS,
)
extract_entities_agent.instrument = True

extract_facts_agent: Agent[None, ExtractedFacts] = Agent(
    name="zeit.extract.facts",
    output_type=ExtractedFacts,
    instructions=FACT_INSTRUCTIONS,
)
extract_facts_agent.instrument = True


def _episode_xml(content: str, prior: Sequence[str]) -> str:
    return format_as_xml(
        {"prior": list(prior), "episode": content},
        root_tag="input",
    )


def _facts_xml(
    content: str, entities: Sequence[ExtractedEntity], prior: Sequence[str]
) -> str:
    return format_as_xml(
        {
            "prior": list(prior),
            "episode": content,
            "entities": [entity.name for entity in entities],
        },
        root_tag="input",
    )


async def extract_entities(
    content: str, *, model: str | Model, prior: Sequence[str] = ()
) -> tuple[ExtractedEntity, ...]:
    result = await extract_entities_agent.run(_episode_xml(content, prior), model=model)
    return tuple(result.output.entities)


async def extract_facts(
    content: str,
    entities: Sequence[ExtractedEntity],
    *,
    model: str | Model,
    prior: Sequence[str] = (),
) -> tuple[ExtractedFact, ...]:
    if not entities:
        return ()
    result = await extract_facts_agent.run(
        _facts_xml(content, entities, prior), model=model
    )
    return tuple(result.output.facts)


async def extract(
    content: str, *, model: str | Model, prior: Sequence[str] = ()
) -> Extraction:
    entities = await extract_entities(content, model=model, prior=prior)
    facts = await extract_facts(content, entities, model=model, prior=prior)
    return Extraction(entities=entities, facts=facts)
