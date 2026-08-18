# Stay current without losing what used to be true

**zeit** is a Python library for building LLM applications.
It turns notes, chats, and events into a knowledge graph your model can search.

Those sources contradict each other.
Most stores overwrite — the model only remembers the latest version.
zeit expires the old fact instead of deleting it.
Your app can retrieve what's true now, and still ask what was true last spring.
Every fact keeps two clocks: when it was true in the world, and when you wrote it down.

## Two clocks

Say you ingest this today:

> Ada works at Acme.

Next month you ingest:

> Ada left Acme for Birch in March.

Most graphs overwrite.
You only remember Birch.

zeit keeps both:

| Fact | True in the world | Written down |
| --- | --- | --- |
| Ada works at Acme | until March | January |
| Ada works at Birch | from March | April |

Ask “where does Ada work?” and you get Birch.
Ask what was true in February and you still get Acme.

## What you do with it

1. **Ingest an episode** from a chat turn, a document, or a fact you already know.
2. zeit pulls out people, things, and claims; two names for the same person become one entity.
3. A contradicting claim expires the old fact, and history stays.
4. **Search** before the next model call. Hits mix meaning, keywords, and nearby graph links; by default the model sees what’s valid now.

## Intended shape

Drop a `Graph` into your LLM app.
The public API is async.
A `Graph` is one SurrealDB namespace + database.

```python
from zeit import Graph

graph = Graph(
    url="ws://localhost:8000/rpc",
    namespace="app",
    database="memory",
    credentials=credentials,
    models=stack,
)

await graph.add_episode("Ada left Acme for Birch in March 2026.")
hits = await graph.search("where does Ada work?")
```

Skip extraction and write a known fact with `add_triplet`.
Look up a stored entity or fact with `get_entity` and `get_fact`.

## Run from this repo

Python 3.14 or newer, and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -c "import zeit; print(zeit.__version__)"
```

Checks:

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run basedpyright
```

## How it runs

zeit is the ingest → resolve → expire → search algorithm.
The current implementation uses:

- **SurrealDB** as the only store
- **PydanticAI** for every LLM call
- **Logfire** for traces — you configure Logfire in your process; zeit does not take a token

Swap the embedder if you want.
The graph API stays the same.

## Status

The package is early: it installs and imports.
The graph API above is the target shape, not a shipped release yet.
