"""Staged ingest pipeline: context, extract, resolve, invalidate, embed, persist."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import final
from uuid import uuid4

from pydantic_ai.models import Model

from .context import EPISODE_WINDOW, recent_episodes
from .embedder import Embedder
from .extract import ExtractedFact, extract
from .invalidate import invalidate
from .resolve import Resolution, resolve
from .store import SurrealStore
from .types import Entity, Episode, Fact, IngestResult, Mention

MAX_CONCURRENCY = 8


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ModelStack:
    extract: str | Model
    resolve: str | Model
    invalidate: str | Model
    embedder: Embedder


@final
class Graph:
    def __init__(
        self,
        url: str,
        namespace: str,
        database: str,
        credentials: Mapping[str, str] | None = None,
        *,
        models: ModelStack,
        episode_window: int = EPISODE_WINDOW,
        max_concurrency: int = MAX_CONCURRENCY,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.episode_window = episode_window
        self.max_concurrency = max_concurrency
        self.models = models
        self.store = SurrealStore(url, namespace, database, credentials)

    async def aclose(self) -> None:
        await self.store.aclose()

    async def add_episode(
        self, content: str, *, now: datetime | None = None
    ) -> IngestResult:
        stamp = now if now is not None else datetime.now(UTC)
        prior_episodes = await recent_episodes(
            self.store, episode_window=self.episode_window
        )
        prior = tuple(episode.content for episode in prior_episodes)
        extraction = await extract(content, model=self.models.extract, prior=prior)
        resolution = await resolve(
            extraction.entities,
            self.store,
            model=self.models.resolve,
            prior=prior,
            now=stamp,
        )
        await invalidate(
            extraction.facts,
            resolution,
            self.store,
            model=self.models.invalidate,
            now=stamp,
        )
        episode = Episode(uuid=uuid4(), content=content, created_at=stamp)
        facts = _facts(extraction.facts, resolution, now=stamp)
        mentions = _mentions(episode, resolution)
        new_entities = await _unsaved(self.store, resolution.entities)
        await self._embed_and_put(episode, new_entities, facts, mentions)
        return IngestResult(
            episode=episode,
            entities=resolution.entities,
            facts=facts,
            mentions=mentions,
        )

    async def _embed_and_put(
        self,
        episode: Episode,
        entities: Sequence[Entity],
        facts: Sequence[Fact],
        mentions: Sequence[Mention],
    ) -> None:
        names = [entity.name for entity in entities]
        statements = [fact.statement for fact in facts]
        texts = names + statements
        vectors = await self.models.embedder.embed(texts) if texts else []
        if texts and len(vectors) != len(texts):
            raise RuntimeError("embedder returned the wrong number of vectors")
        await self.store.put(episode)
        offset = 0
        for entity in entities:
            await self.store.put(entity, embedding=vectors[offset])
            offset += 1
        for fact in facts:
            await self.store.put(fact, embedding=vectors[offset])
            offset += 1
        for mention in mentions:
            await self.store.put(mention)


def _bound(resolution: Resolution) -> dict[str, Entity]:
    names = {entity.name: entity for entity in resolution.entities}
    for item in resolution.bindings:
        names[item.surface] = item.entity
    return names


def _facts(
    extracted: Sequence[ExtractedFact],
    resolution: Resolution,
    *,
    now: datetime,
) -> tuple[Fact, ...]:
    names = _bound(resolution)
    facts: list[Fact] = []
    for item in extracted:
        subject = names.get(item.subject)
        obj = names.get(item.object)
        if subject is None or obj is None:
            continue
        facts.append(
            Fact(
                uuid=uuid4(),
                subject_id=subject.uuid,
                predicate=item.predicate,
                object_id=obj.uuid,
                statement=item.statement,
                valid_at=item.valid_at if item.valid_at is not None else now,
                invalid_at=None,
                created_at=now,
                expired_at=None,
            )
        )
    return tuple(facts)


def _mentions(episode: Episode, resolution: Resolution) -> tuple[Mention, ...]:
    return tuple(
        Mention(
            uuid=uuid4(),
            episode_id=episode.uuid,
            entity_id=item.entity.uuid,
            surface=item.surface,
        )
        for item in resolution.bindings
    )


async def _unsaved(
    store: SurrealStore, entities: Sequence[Entity]
) -> tuple[Entity, ...]:
    new: list[Entity] = []
    for entity in entities:
        if await store.get(Entity, entity.uuid) is None:
            new.append(entity)
    return tuple(new)
