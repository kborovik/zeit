import inspect
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings

from conftest import open_graph
from zeit import Entity, Fact, Graph, ModelStack, SearchHits

NOW = datetime(2026, 3, 1, tzinfo=UTC)
LATER = datetime(2026, 4, 1, tzinfo=UTC)


class _Boom(TestModel):
    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        raise AssertionError("search must not call the model")


class _RecordEmbedder:
    def __init__(self, vector: list[float] | None = None) -> None:
        self.texts: list[str] = []
        self._vector = vector if vector is not None else [1.0, 0.0]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [list(self._vector) for _ in texts]


def _entity(name: str, *, created_at: datetime = NOW) -> Entity:
    return Entity(uuid=uuid4(), name=name, created_at=created_at)


def _fact(
    subject: Entity,
    obj: Entity,
    *,
    statement: str,
    predicate: str = "works_at",
    invalid_at: datetime | None = None,
    expired_at: datetime | None = None,
) -> Fact:
    return Fact(
        uuid=uuid4(),
        subject_id=subject.uuid,
        predicate=predicate,
        object_id=obj.uuid,
        statement=statement,
        valid_at=NOW,
        invalid_at=invalid_at,
        created_at=NOW,
        expired_at=expired_at,
    )


def _graph(url: str, embedder: _RecordEmbedder | None = None) -> Graph:
    recorded = embedder if embedder is not None else _RecordEmbedder()
    return open_graph(
        url,
        models=ModelStack(
            extract=_Boom(),
            resolve=_Boom(),
            invalidate=_Boom(),
            embedder=recorded,
        ),
    )


@pytest.fixture
async def closing() -> AsyncIterator[list[Graph]]:
    opened: list[Graph] = []
    yield opened
    for graph in opened:
        await graph.aclose()


async def _put_entity(
    graph: Graph, entity: Entity, *, embedding: list[float] | None = None
) -> None:
    await graph.store.put(entity, embedding=embedding)


async def _put_fact(
    graph: Graph, fact: Fact, *, embedding: list[float] | None = None
) -> None:
    await graph.store.put(fact, embedding=embedding)


def _ids(records: tuple[Entity, ...] | tuple[Fact, ...]) -> set[UUID]:
    return {record.uuid for record in records}


async def test_search_embeds_query_and_fuses_text_and_vector(
    closing: list[Graph],
    brew_surreal_url: str,
) -> None:
    embedder = _RecordEmbedder([1.0, 0.0])
    graph = _graph(brew_surreal_url, embedder)
    closing.append(graph)
    ada = _entity("Ada")
    acme = _entity("Acme")
    bob = _entity("Bob")
    birch = _entity("Birch")
    text_hit = _fact(ada, acme, statement="Ada works at Acme.")
    vector_hit = _fact(
        bob, birch, statement="someone founded Birch.", predicate="founded"
    )
    await _put_entity(graph, ada)
    await _put_entity(graph, acme)
    await _put_entity(graph, bob)
    await _put_entity(graph, birch)
    await _put_fact(graph, text_hit, embedding=[0.0, 1.0])
    await _put_fact(graph, vector_hit, embedding=[1.0, 0.0])
    hits = await graph.search("Ada")
    assert embedder.texts == ["Ada"]
    assert isinstance(hits, SearchHits)
    assert text_hit.uuid in _ids(hits.facts)
    assert vector_hit.uuid in _ids(hits.facts)


async def test_search_valid_now_default_excludes_expired(
    closing: list[Graph],
    brew_surreal_url: str,
) -> None:
    graph = _graph(brew_surreal_url)
    closing.append(graph)
    ada = _entity("Ada")
    acme = _entity("Acme")
    birch = _entity("Birch")
    expired = _fact(
        ada,
        acme,
        statement="Ada works at Acme.",
        invalid_at=NOW,
        expired_at=LATER,
    )
    open_fact = _fact(ada, birch, statement="Ada works at Birch.")
    await _put_entity(graph, ada)
    await _put_entity(graph, acme)
    await _put_entity(graph, birch)
    await _put_fact(graph, expired, embedding=[1.0, 0.0])
    await _put_fact(graph, open_fact, embedding=[1.0, 0.0])
    default_hits = await graph.search("Ada")
    assert open_fact.uuid in _ids(default_hits.facts)
    assert expired.uuid not in _ids(default_hits.facts)
    history = await graph.search("Ada", valid_now=False)
    assert open_fact.uuid in _ids(history.facts)
    assert expired.uuid in _ids(history.facts)


async def test_search_one_hop_expands_entity_and_fact(
    closing: list[Graph],
    brew_surreal_url: str,
) -> None:
    graph = _graph(brew_surreal_url)
    closing.append(graph)
    ada = _entity("Ada")
    acme = _entity("Acme")
    person = _entity("Person-1")
    corp = _entity("Corp-X")
    neighbor = _fact(ada, acme, statement="founded Birch in 2020.", predicate="founded")
    text_fact = _fact(person, corp, statement="Ada works at Acme.")
    await _put_entity(graph, ada)
    await _put_entity(graph, acme)
    await _put_entity(graph, person)
    await _put_entity(graph, corp)
    await _put_fact(graph, neighbor)
    await _put_fact(graph, text_fact, embedding=[1.0, 0.0])
    hits = await graph.search("Ada")
    assert neighbor.uuid in _ids(hits.facts)
    assert text_fact.uuid in _ids(hits.facts)
    assert ada.uuid in _ids(hits.entities)
    assert person.uuid in _ids(hits.entities)
    assert corp.uuid in _ids(hits.entities)


async def test_get_entity_and_get_fact(
    closing: list[Graph], brew_surreal_url: str
) -> None:
    graph = _graph(brew_surreal_url)
    closing.append(graph)
    ada = _entity("Ada")
    acme = _entity("Acme")
    fact = _fact(ada, acme, statement="Ada works at Acme.")
    await _put_entity(graph, ada)
    await _put_entity(graph, acme)
    await _put_fact(graph, fact)
    assert await graph.get_entity(ada.uuid) == ada
    assert await graph.get_fact(fact.uuid) == fact
    assert await graph.get_entity(uuid4()) is None
    assert await graph.get_fact(uuid4()) is None


def test_search_and_getter_signatures() -> None:
    search = inspect.signature(Graph.search).parameters
    assert list(search) == ["self", "query", "valid_now"]
    assert search["valid_now"].default is True
    assert inspect.iscoroutinefunction(Graph.search)
    assert list(inspect.signature(Graph.get_entity).parameters) == ["self", "uuid"]
    assert list(inspect.signature(Graph.get_fact).parameters) == ["self", "uuid"]
    assert inspect.iscoroutinefunction(Graph.get_entity)
    assert inspect.iscoroutinefunction(Graph.get_fact)
