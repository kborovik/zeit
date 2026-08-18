"""Staged ingest plus hybrid search and uuid getters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import final
from uuid import UUID, uuid4

from pydantic_ai.models import Model

from .context import EPISODE_WINDOW, recent_episodes
from .embedder import Embedder, PydanticAIEmbedder
from .extract import ExtractedEntity, ExtractedFact, Extraction, extract
from .invalidate import invalidate
from .resolve import Resolution, resolve
from .store import SurrealStore
from .types import Entity, Episode, Fact, IngestResult, Mention, SearchHits

MAX_CONCURRENCY = 8
DEFAULT_MODEL = "google:gemini-3.7-flash"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ModelStack:
    extract: str | Model = DEFAULT_MODEL
    resolve: str | Model = DEFAULT_MODEL
    invalidate: str | Model = DEFAULT_MODEL
    embedder: Embedder = field(default_factory=PydanticAIEmbedder)


@final
class Graph:
    def __init__(
        self,
        url: str,
        namespace: str,
        database: str,
        credentials: Mapping[str, str] | None = None,
        *,
        models: ModelStack | None = None,
        episode_window: int = EPISODE_WINDOW,
        max_concurrency: int = MAX_CONCURRENCY,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.episode_window = episode_window
        self.max_concurrency = max_concurrency
        self.models = models if models is not None else ModelStack()
        self.store = SurrealStore(url, namespace, database, credentials)

    async def aclose(self) -> None:
        await self.store.aclose()

    async def add_episode(
        self, content: str, *, now: datetime | None = None
    ) -> IngestResult:
        stamp = now if now is not None else datetime.now(UTC)
        prior = await self._prior()
        extraction = await extract(content, model=self.models.extract, prior=prior)
        return await self._ingest(extraction, content=content, prior=prior, now=stamp)

    async def add_triplet(
        self,
        subject: str,
        predicate: str,
        object: str,
        statement: str,
        *,
        valid_at: datetime | None = None,
        now: datetime | None = None,
    ) -> IngestResult:
        stamp = now if now is not None else datetime.now(UTC)
        prior = await self._prior()
        extraction = Extraction(
            entities=(
                ExtractedEntity(name=subject),
                ExtractedEntity(name=object),
            ),
            facts=(
                ExtractedFact(
                    subject=subject,
                    predicate=predicate,
                    object=object,
                    statement=statement,
                    valid_at=valid_at,
                ),
            ),
        )
        return await self._ingest(extraction, content=None, prior=prior, now=stamp)

    async def search(self, query: str, *, valid_now: bool = True) -> SearchHits:
        vectors = await self.models.embedder.embed([query])
        if len(vectors) != 1:
            raise RuntimeError("embedder returned the wrong number of vectors")
        hits = await self.store.search(query, vectors[0], valid_now=valid_now)
        return await _one_hop(self.store, hits, valid_now=valid_now)

    async def get_entity(self, uuid: UUID) -> Entity | None:
        return await self.store.get(Entity, uuid)

    async def get_fact(self, uuid: UUID) -> Fact | None:
        return await self.store.get(Fact, uuid)

    async def _prior(self) -> tuple[str, ...]:
        prior_episodes = await recent_episodes(
            self.store, episode_window=self.episode_window
        )
        return tuple(episode.content for episode in prior_episodes)

    async def _ingest(
        self,
        extraction: Extraction,
        *,
        content: str | None,
        prior: Sequence[str],
        now: datetime,
    ) -> IngestResult:
        resolution = await resolve(
            extraction.entities,
            self.store,
            model=self.models.resolve,
            prior=prior,
            now=now,
        )
        await invalidate(
            extraction.facts,
            resolution,
            self.store,
            model=self.models.invalidate,
            now=now,
        )
        episode = (
            Episode(uuid=uuid4(), content=content, created_at=now)
            if content is not None
            else None
        )
        facts = _facts(extraction.facts, resolution, now=now)
        mentions = _mentions(episode, resolution) if episode is not None else ()
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
        episode: Episode | None,
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
        if episode is not None:
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


async def _one_hop(
    store: SurrealStore, hits: SearchHits, *, valid_now: bool
) -> SearchHits:
    seen_facts = {fact.uuid: fact for fact in hits.facts}
    seen_entities = {entity.uuid: entity for entity in hits.entities}
    seed_ids = list(seen_entities)
    for fact in hits.facts:
        seed_ids.append(fact.subject_id)
        seed_ids.append(fact.object_id)
    extra_facts: list[Fact] = []
    for fact in await store.open_facts(seed_ids, valid_now=valid_now):
        if fact.uuid in seen_facts:
            continue
        seen_facts[fact.uuid] = fact
        extra_facts.append(fact)
    extra_entities: list[Entity] = []
    needed = list(seen_entities)
    for fact in (*hits.facts, *extra_facts):
        needed.append(fact.subject_id)
        needed.append(fact.object_id)
    for entity_id in dict.fromkeys(needed):
        if entity_id in seen_entities:
            continue
        entity = await store.get(Entity, entity_id)
        if entity is None:
            continue
        seen_entities[entity_id] = entity
        extra_entities.append(entity)
    return SearchHits(
        facts=(*hits.facts, *extra_facts),
        entities=(*hits.entities, *extra_entities),
    )
