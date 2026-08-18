"""Text embedder protocol and PydanticAI implementation."""

from typing import Protocol, runtime_checkable

from pydantic_ai import Embedder as PydanticAI
from pydantic_ai.embeddings import EmbeddingModel

DEFAULT_EMBEDDER_MODEL = "google:gemini-embedding-2"


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class PydanticAIEmbedder:
    def __init__(self, model: str | EmbeddingModel = DEFAULT_EMBEDDER_MODEL) -> None:
        self._inner = PydanticAI(model, instrument=True)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result = await self._inner.embed_documents(texts)
        return [list(vector) for vector in result.embeddings]
