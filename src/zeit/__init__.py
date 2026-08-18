"""Most knowledge graphs overwrite when facts change.

zeit expires the old fact instead, so you can search what's true now and still
ask what was true last spring.
"""

from .embedder import Embedder, PydanticAIEmbedder
from .store import Store, SurrealStore
from .types import Entity, Episode, Fact, IngestResult, Mention, SearchHits

__version__ = "0.1.0"

__all__ = [
    "Embedder",
    "Entity",
    "Episode",
    "Fact",
    "IngestResult",
    "Mention",
    "PydanticAIEmbedder",
    "SearchHits",
    "Store",
    "SurrealStore",
]
