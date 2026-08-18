"""Last-N episode context window for extract and resolve."""

from .store import SurrealStore
from .types import Episode

EPISODE_WINDOW = 3


async def recent_episodes(
    store: SurrealStore, *, episode_window: int = EPISODE_WINDOW
) -> tuple[Episode, ...]:
    return await store.recent_episodes(episode_window)
