from pydantic_ai.embeddings import TestEmbeddingModel

from zeit import Embedder, PydanticAIEmbedder


class _FixedEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(index)] for index, _ in enumerate(texts)]


async def _run(embedder: Embedder, texts: list[str]) -> list[list[float]]:
    return await embedder.embed(texts)


def test_embedder_exports_from_zeit() -> None:
    assert Embedder.__module__ == "zeit.embedder"
    assert PydanticAIEmbedder.__module__ == "zeit.embedder"


def test_pydantic_ai_embedder_satisfies_protocol() -> None:
    impl = PydanticAIEmbedder(TestEmbeddingModel())
    assert isinstance(impl, Embedder)


async def test_caller_may_swap_embedder() -> None:
    swapped = _FixedEmbedder()
    assert isinstance(swapped, Embedder)
    assert await _run(swapped, ["Ada", "Acme"]) == [[0.0], [1.0]]


async def test_pydantic_ai_embedder_returns_one_vector_per_text() -> None:
    impl = PydanticAIEmbedder(TestEmbeddingModel(dimensions=4))
    vectors = await impl.embed(["Ada left Acme.", "Ada works at Birch."])
    assert vectors == [[1.0, 1.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]]
    assert all(isinstance(value, float) for vector in vectors for value in vector)


async def test_pydantic_ai_embedder_empty_input() -> None:
    impl = PydanticAIEmbedder(TestEmbeddingModel())
    assert await impl.embed([]) == []
