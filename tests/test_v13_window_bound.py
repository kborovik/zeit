from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel

from zeit import EPISODE_WINDOW, Episode, SurrealStore, recent_episodes
from zeit.extract import extract_entities

NOW = datetime(2026, 3, 1, tzinfo=UTC)


@pytest.fixture
async def store() -> AsyncIterator[SurrealStore]:
    impl = SurrealStore("mem://", "app", "memory")
    yield impl
    await impl.aclose()


def _episode(offset: int, content: str) -> Episode:
    return Episode(
        uuid=uuid4(),
        content=content,
        created_at=NOW + timedelta(days=offset),
    )


async def _put(store: SurrealStore, *episodes: Episode) -> None:
    for episode in episodes:
        await store.put(episode)


def test_episode_window_default_is_three() -> None:
    assert EPISODE_WINDOW == 3


async def test_recent_episodes_returns_last_n_oldest_first(store: SurrealStore) -> None:
    first = _episode(0, "Ada joined Acme.")
    second = _episode(1, "Ada left Acme.")
    third = _episode(2, "Ada joined Birch.")
    fourth = _episode(3, "Birch hired Ada.")
    fifth = _episode(4, "Ada leads Birch.")
    await _put(store, first, second, third, fourth, fifth)
    window = await recent_episodes(store, episode_window=3)
    assert window == (third, fourth, fifth)


async def test_recent_episodes_default_limit_is_episode_window(
    store: SurrealStore,
) -> None:
    episodes = tuple(_episode(index, f"note {index}") for index in range(5))
    await _put(store, *episodes)
    window = await recent_episodes(store)
    assert window == episodes[-EPISODE_WINDOW:]


async def test_recent_episodes_fewer_than_window(store: SurrealStore) -> None:
    first = _episode(0, "Ada joined Acme.")
    second = _episode(1, "Ada left Acme.")
    await _put(store, first, second)
    assert await recent_episodes(store) == (first, second)


async def test_recent_episodes_empty_store(store: SurrealStore) -> None:
    assert await recent_episodes(store) == ()


async def test_recent_episodes_zero_window(store: SurrealStore) -> None:
    await store.put(_episode(0, "Ada joined Acme."))
    assert await recent_episodes(store, episode_window=0) == ()


async def test_recent_episodes_rejects_negative_window(store: SurrealStore) -> None:
    with pytest.raises(ValueError, match="limit must be >= 0"):
        await recent_episodes(store, episode_window=-1)


async def test_recent_episodes_stay_in_one_database() -> None:
    memory = SurrealStore("mem://", "app", "memory")
    other = SurrealStore("mem://", "app", "other")
    try:
        episode = _episode(0, "Ada joined Acme.")
        await memory.put(episode)
        assert await recent_episodes(memory) == (episode,)
        assert await recent_episodes(other) == ()
    finally:
        await memory.aclose()
        await other.aclose()


async def test_recent_episodes_feed_extract_prior(store: SurrealStore) -> None:
    prior_episode = _episode(0, "Ada works at Acme.")
    await store.put(prior_episode)
    prior = tuple(item.content for item in await recent_episodes(store))
    with capture_run_messages() as messages:
        await extract_entities(
            "Ada left Acme.",
            model=TestModel(custom_output_args={"entities": [{"name": "Ada"}]}),
            prior=prior,
        )
    requests = [item for item in messages if isinstance(item, ModelRequest)]
    assert requests
    part = requests[0].parts[0]
    assert isinstance(part, UserPromptPart)
    assert isinstance(part.content, str)
    assert "Ada works at Acme." in part.content
    assert "Ada left Acme." in part.content
