import inspect
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.settings import ModelSettings

from conftest import open_graph
from zeit import EPISODE_WINDOW, Entity, Episode, Fact, Graph, Mention, ModelStack

NOW = datetime(2026, 3, 1, tzinfo=UTC)
APRIL = datetime(2026, 4, 1, tzinfo=UTC)


class _ExtractModel(TestModel):
    def __init__(
        self,
        entities: list[dict[str, object]],
        facts: list[dict[str, object]],
    ) -> None:
        super().__init__()
        self._entities = entities
        self._facts = facts
        self.calls = 0

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            self.custom_output_args = {"entities": self._entities}
        else:
            self.custom_output_args = {"facts": self._facts}
        return await super().request(messages, model_settings, model_request_parameters)


class _ScriptedExtract(TestModel):
    def __init__(
        self,
        scripts: list[tuple[list[dict[str, object]], list[dict[str, object]]]],
    ) -> None:
        super().__init__()
        self._scripts = scripts
        self.calls = 0

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        entities, facts = self._scripts[self.calls // 2]
        if self.calls % 2 == 0:
            self.custom_output_args = {"entities": entities}
        else:
            self.custom_output_args = {"facts": facts}
        self.calls += 1
        return await super().request(messages, model_settings, model_request_parameters)


class _Boom(TestModel):
    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        raise AssertionError("pipeline stage must not call the model")


class _RecordEmbedder:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[float(index), 1.0] for index, _ in enumerate(texts)]


def _entities(*names: str) -> list[dict[str, object]]:
    return [{"name": name} for name in names]


def _fact_args(
    subject: str,
    predicate: str,
    obj: str,
    statement: str,
    *,
    valid_at: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "statement": statement,
    }
    if valid_at is not None:
        payload["valid_at"] = valid_at
    return payload


def _stack(
    *,
    extract: TestModel | None = None,
    resolve: TestModel | None = None,
    invalidate: TestModel | None = None,
    embedder: _RecordEmbedder | None = None,
) -> tuple[ModelStack, _RecordEmbedder]:
    recorded = embedder if embedder is not None else _RecordEmbedder()
    return (
        ModelStack(
            extract=extract
            or _ExtractModel(
                _entities("Ada", "Acme"),
                [
                    _fact_args(
                        "Ada",
                        "works_at",
                        "Acme",
                        "Ada works at Acme.",
                    )
                ],
            ),
            resolve=resolve or TestModel(custom_output_args={"existing_name": None}),
            invalidate=invalidate or _Boom(),
            embedder=recorded,
        ),
        recorded,
    )


def _graph(
    url: str, models: ModelStack, *, episode_window: int = EPISODE_WINDOW
) -> Graph:
    return open_graph(url, models=models, episode_window=episode_window)


@pytest.fixture
async def closing() -> AsyncIterator[list[Graph]]:
    opened: list[Graph] = []
    yield opened
    for graph in opened:
        await graph.aclose()


async def test_add_episode_runs_staged_pipeline(
    closing: list[Graph], brew_surreal_url: str
) -> None:
    models, embedder = _stack()
    graph = _graph(brew_surreal_url, models)
    closing.append(graph)
    result = await graph.add_episode("Ada works at Acme.", now=NOW)
    assert result.episode is not None
    assert result.episode.content == "Ada works at Acme."
    assert result.episode.created_at == NOW
    assert [entity.name for entity in result.entities] == ["Ada", "Acme"]
    assert len(result.facts) == 1
    assert result.facts[0].statement == "Ada works at Acme."
    assert result.facts[0].predicate == "works_at"
    assert result.facts[0].subject_id == result.entities[0].uuid
    assert result.facts[0].object_id == result.entities[1].uuid
    assert result.facts[0].valid_at == NOW
    assert result.facts[0].invalid_at is None
    assert result.facts[0].expired_at is None
    assert [mention.surface for mention in result.mentions] == ["Ada", "Acme"]
    assert embedder.texts == ["Ada", "Acme", "Ada works at Acme."]
    stored_episode = await graph.store.get(Episode, result.episode.uuid)
    assert stored_episode == result.episode
    assert await graph.store.get(Entity, result.entities[0].uuid) == result.entities[0]
    assert await graph.store.get(Fact, result.facts[0].uuid) == result.facts[0]
    assert await graph.store.get(Mention, result.mentions[0].uuid) == result.mentions[0]


async def test_add_episode_feeds_prior_context_to_extract(
    closing: list[Graph], brew_surreal_url: str
) -> None:
    models, _ = _stack()
    graph = _graph(brew_surreal_url, models, episode_window=2)
    closing.append(graph)
    await graph.store.put(
        Episode(uuid=uuid4(), content="Ada joined Acme.", created_at=NOW)
    )
    await graph.store.put(
        Episode(uuid=uuid4(), content="Ada leads engineering.", created_at=APRIL)
    )
    with capture_run_messages() as messages:
        await graph.add_episode("Ada works at Acme.", now=APRIL)
    requests = [item for item in messages if isinstance(item, ModelRequest)]
    assert requests
    part = requests[0].parts[0]
    assert isinstance(part, UserPromptPart)
    assert isinstance(part.content, str)
    assert "Ada joined Acme." in part.content
    assert "Ada leads engineering." in part.content
    assert "Ada works at Acme." in part.content


async def test_add_episode_resolves_and_invalidates(
    closing: list[Graph], brew_surreal_url: str
) -> None:
    extract = _ScriptedExtract(
        [
            (
                _entities("Ada", "Acme"),
                [_fact_args("Ada", "works_at", "Acme", "Ada works at Acme.")],
            ),
            (
                _entities("Ada", "Birch"),
                [
                    _fact_args(
                        "Ada",
                        "works_at",
                        "Birch",
                        "Ada works at Birch.",
                        valid_at="2026-03-01T00:00:00Z",
                    )
                ],
            ),
        ]
    )
    models, _ = _stack(
        extract=extract,
        invalidate=TestModel(custom_output_args={"statements": ["Ada works at Acme."]}),
    )
    graph = _graph(brew_surreal_url, models)
    closing.append(graph)
    first = await graph.add_episode("Ada works at Acme.", now=NOW)
    second = await graph.add_episode("Ada left Acme for Birch in March.", now=APRIL)
    assert first.entities[0].uuid == second.entities[0].uuid
    assert first.entities[0].name == "Ada"
    assert {entity.name for entity in second.entities} == {"Ada", "Birch"}
    old = await graph.store.get(Fact, first.facts[0].uuid)
    assert old is not None
    assert old.invalid_at == NOW
    assert old.expired_at == APRIL
    assert old.valid_at == NOW
    assert old.created_at == NOW
    assert old.statement == "Ada works at Acme."
    new = await graph.store.get(Fact, second.facts[0].uuid)
    assert new == second.facts[0]
    assert new is not None
    assert new.invalid_at is None
    assert new.expired_at is None


async def test_add_episode_empty_extract_still_persists_episode(
    closing: list[Graph],
    brew_surreal_url: str,
) -> None:
    embedder = _RecordEmbedder()
    models, _ = _stack(
        extract=TestModel(custom_output_args={"entities": []}),
        embedder=embedder,
    )
    graph = _graph(brew_surreal_url, models)
    closing.append(graph)
    result = await graph.add_episode("hmm.", now=NOW)
    assert result.episode is not None
    assert result.episode.content == "hmm."
    assert result.entities == ()
    assert result.facts == ()
    assert result.mentions == ()
    assert embedder.texts == []
    assert await graph.store.get(Episode, result.episode.uuid) == result.episode


async def test_add_episode_drops_facts_with_unbound_names(
    closing: list[Graph], brew_surreal_url: str
) -> None:
    models, _ = _stack(
        extract=_ExtractModel(
            _entities("Ada"),
            [_fact_args("Ada", "works_at", "Acme", "Ada works at Acme.")],
        )
    )
    graph = _graph(brew_surreal_url, models)
    closing.append(graph)
    result = await graph.add_episode("Ada works at Acme.", now=NOW)
    assert [entity.name for entity in result.entities] == ["Ada"]
    assert result.facts == ()


def test_graph_exports_and_ctor_shape() -> None:
    assert Graph.__module__ == "zeit.graph"
    assert ModelStack.__module__ == "zeit.graph"
    params = inspect.signature(Graph.__init__).parameters
    assert "url" in params
    assert "namespace" in params
    assert "database" in params
    assert "credentials" in params
    assert "models" in params
    assert "episode_window" in params
    assert "max_concurrency" in params
    assert "token" not in params
    assert "logfire" not in params
    assert params["models"].default is None
    assert params["episode_window"].default == EPISODE_WINDOW


async def test_add_triplet_skips_extract_and_persists(
    closing: list[Graph], brew_surreal_url: str
) -> None:
    models, embedder = _stack(extract=_Boom())
    graph = _graph(brew_surreal_url, models)
    closing.append(graph)
    result = await graph.add_triplet(
        "Ada",
        "works_at",
        "Acme",
        "Ada works at Acme.",
        now=NOW,
    )
    assert result.episode is None
    assert result.mentions == ()
    assert [entity.name for entity in result.entities] == ["Ada", "Acme"]
    assert len(result.facts) == 1
    assert result.facts[0].statement == "Ada works at Acme."
    assert result.facts[0].predicate == "works_at"
    assert result.facts[0].subject_id == result.entities[0].uuid
    assert result.facts[0].object_id == result.entities[1].uuid
    assert result.facts[0].valid_at == NOW
    assert result.facts[0].invalid_at is None
    assert result.facts[0].expired_at is None
    assert embedder.texts == ["Ada", "Acme", "Ada works at Acme."]
    assert await graph.store.get(Entity, result.entities[0].uuid) == result.entities[0]
    assert await graph.store.get(Fact, result.facts[0].uuid) == result.facts[0]


async def test_add_triplet_uses_valid_at_and_now(
    closing: list[Graph], brew_surreal_url: str
) -> None:
    models, _ = _stack(extract=_Boom())
    graph = _graph(brew_surreal_url, models)
    closing.append(graph)
    result = await graph.add_triplet(
        "Ada",
        "works_at",
        "Acme",
        "Ada works at Acme.",
        valid_at=NOW,
        now=APRIL,
    )
    assert result.facts[0].valid_at == NOW
    assert result.facts[0].created_at == APRIL


async def test_add_triplet_resolves_and_invalidates(
    closing: list[Graph], brew_surreal_url: str
) -> None:
    models, _ = _stack(
        extract=_Boom(),
        invalidate=TestModel(custom_output_args={"statements": ["Ada works at Acme."]}),
    )
    graph = _graph(brew_surreal_url, models)
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
    assert first.entities[0].uuid == second.entities[0].uuid
    assert first.entities[0].name == "Ada"
    assert {entity.name for entity in second.entities} == {"Ada", "Birch"}
    old = await graph.store.get(Fact, first.facts[0].uuid)
    assert old is not None
    assert old.invalid_at == NOW
    assert old.expired_at == APRIL
    assert old.valid_at == NOW
    assert old.created_at == NOW
    assert old.statement == "Ada works at Acme."
    new = await graph.store.get(Fact, second.facts[0].uuid)
    assert new == second.facts[0]
    assert new is not None
    assert new.invalid_at is None
    assert new.expired_at is None


def test_add_triplet_signature() -> None:
    params = inspect.signature(Graph.add_triplet).parameters
    assert list(params) == [
        "self",
        "subject",
        "predicate",
        "object",
        "statement",
        "valid_at",
        "now",
    ]
    assert inspect.iscoroutinefunction(Graph.add_triplet)
