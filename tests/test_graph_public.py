from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings

from zeit import Entity, Fact, Graph, IngestResult, ModelStack

NOW = datetime(2026, 3, 1, tzinfo=UTC)
APRIL = datetime(2026, 4, 1, tzinfo=UTC)


class _Boom(TestModel):
    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        raise AssertionError("stage must not call the model")


class _MergeAda(TestModel):
    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        if "<name>Ada Lovelace</name>" in _user_text(messages):
            self.custom_output_args = {"existing_name": "Ada"}
        else:
            self.custom_output_args = {"existing_name": None}
        return await super().request(messages, model_settings, model_request_parameters)


class _FixedEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def _user_text(messages: list[ModelMessage]) -> str:
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                return part.content
    return ""


def _stack(
    *,
    resolve: TestModel | None = None,
    invalidate: TestModel | None = None,
) -> ModelStack:
    return ModelStack(
        extract=_Boom(),
        resolve=resolve or TestModel(custom_output_args={"existing_name": None}),
        invalidate=invalidate or _Boom(),
        embedder=_FixedEmbedder(),
    )


def _graph(models: ModelStack, *, database: str = "memory") -> Graph:
    return Graph("mem://", "app", database, models=models)


@pytest.fixture
async def closing() -> AsyncIterator[list[Graph]]:
    opened: list[Graph] = []
    yield opened
    for graph in opened:
        await graph.aclose()


def _ids(records: tuple[Entity, ...] | tuple[Fact, ...]) -> set[UUID]:
    return {record.uuid for record in records}


def _named(result: IngestResult, name: str) -> Entity:
    for entity in result.entities:
        if entity.name == name:
            return entity
    raise AssertionError(f"missing entity {name!r}")


async def test_contradiction_expires_fact_without_drop(closing: list[Graph]) -> None:
    graph = _graph(
        _stack(
            invalidate=TestModel(
                custom_output_args={"statements": ["Ada works at Acme."]}
            ),
        )
    )
    closing.append(graph)
    first = await graph.add_triplet(
        "Ada",
        "works_at",
        "Acme",
        "Ada works at Acme.",
        now=NOW,
    )
    second = await graph.add_triplet(
        "Ada",
        "works_at",
        "Birch",
        "Ada works at Birch.",
        valid_at=NOW,
        now=APRIL,
    )
    old = await graph.get_fact(first.facts[0].uuid)
    assert old is not None
    assert old.uuid == first.facts[0].uuid
    assert old.invalid_at == NOW
    assert old.expired_at == APRIL
    assert old.valid_at == NOW
    assert old.created_at == NOW
    assert old.statement == "Ada works at Acme."
    new = await graph.get_fact(second.facts[0].uuid)
    assert new is not None
    assert new.invalid_at is None
    assert new.expired_at is None


async def test_alias_surface_merges_to_one_entity_uuid(closing: list[Graph]) -> None:
    graph = _graph(
        _stack(
            resolve=_MergeAda(),
            invalidate=TestModel(custom_output_args={"statements": []}),
        )
    )
    closing.append(graph)
    first = await graph.add_triplet(
        "Ada",
        "works_at",
        "Acme",
        "Ada works at Acme.",
        now=NOW,
    )
    second = await graph.add_triplet(
        "Ada Lovelace",
        "works_at",
        "Acme",
        "Ada Lovelace works at Acme.",
        now=APRIL,
    )
    ada = _named(first, "Ada")
    acme = _named(first, "Acme")
    assert {entity.uuid for entity in second.entities} == {ada.uuid, acme.uuid}
    assert second.facts[0].subject_id == ada.uuid
    assert second.facts[0].object_id == acme.uuid
    assert await graph.get_entity(ada.uuid) == ada


async def test_other_graph_database_is_invisible(closing: list[Graph]) -> None:
    memory = _graph(_stack(), database="memory")
    other = _graph(_stack(), database="other")
    closing.extend((memory, other))
    result = await memory.add_triplet(
        "Ada",
        "works_at",
        "Acme",
        "Ada works at Acme.",
        now=NOW,
    )
    ada = _named(result, "Ada")
    fact = result.facts[0]
    assert memory.store.namespace == "app"
    assert memory.store.database == "memory"
    assert other.store.database == "other"
    assert await memory.get_entity(ada.uuid) == ada
    assert await memory.get_fact(fact.uuid) == fact
    assert await other.get_entity(ada.uuid) is None
    assert await other.get_fact(fact.uuid) is None
    hits = await other.search("Ada")
    assert hits.facts == ()
    assert hits.entities == ()


async def test_search_valid_now_excludes_expired_after_ingest(
    closing: list[Graph],
) -> None:
    graph = _graph(
        _stack(
            invalidate=TestModel(
                custom_output_args={"statements": ["Ada works at Acme."]}
            ),
        )
    )
    closing.append(graph)
    first = await graph.add_triplet(
        "Ada",
        "works_at",
        "Acme",
        "Ada works at Acme.",
        now=NOW,
    )
    second = await graph.add_triplet(
        "Ada",
        "works_at",
        "Birch",
        "Ada works at Birch.",
        valid_at=NOW,
        now=APRIL,
    )
    default_hits = await graph.search("Ada")
    assert first.facts[0].uuid not in _ids(default_hits.facts)
    assert second.facts[0].uuid in _ids(default_hits.facts)
    history = await graph.search("Ada", valid_now=False)
    assert first.facts[0].uuid in _ids(history.facts)
    assert second.facts[0].uuid in _ids(history.facts)
