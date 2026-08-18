# Bi-Temporal Knowledge Graph

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
4. **Search** before the next model call: hits mix meaning, keywords, and nearby graph links; by default the model sees what’s valid now.

## Install

Install the PyPI package `zeit-graph`.
The import name is `zeit`.
Python 3.14 or newer is required.
Every public method is async.

```bash
uv add zeit-graph
```

## Construct a Graph

One `Graph` is one SurrealDB namespace plus database.
Records have no tenant field.
Other databases are invisible through this `Graph`.

Configure Logfire before you construct `Graph` if you want traces.
Do not pass a Logfire token to `Graph`.
Do not call `logfire.instrument_pydantic_ai`.
zeit instruments PydanticAI after you configure.

Default Gemini models read `GEMINI_API_KEY`.

```python
import logfire
from zeit import Graph

logfire.configure()

graph = Graph(
    url="ws://127.0.0.1:8000/rpc",
    namespace="app",
    database="memory",
    credentials={"username": "root", "password": "root"},
)

hits = await graph.search("where does Ada work?")
await graph.aclose()
```

`credentials` is optional.
Pass `models=ModelStack(...)` to override extract, resolve, invalidate, or the embedder.
`episode_window` defaults to `3`.
`max_concurrency` defaults to `8`.

## Ingest

`add_episode` extracts people, things, and claims from text, then resolves, invalidates, embeds, and persists.

```python
result = await graph.add_episode("Ada left Acme for Birch in March 2026.")
```

`add_triplet` skips extract and writes a known subject-predicate-object claim.

```python
result = await graph.add_triplet(
    "Ada",
    "works_at",
    "Birch",
    "Ada works at Birch.",
)
```

Both return `IngestResult` with `episode`, `entities`, `facts`, and `mentions`.
`add_triplet` leaves `episode` as `None`.
Two surface forms of the same entity in one database become one `Entity` uuid.

## Clocks

`Fact.valid_at` and `Fact.invalid_at` are world time.
`Fact.created_at` and `Fact.expired_at` are transaction time.
A contradicting claim sets `invalid_at` and `expired_at` on the old row.
zeit does not drop the old row.

Pass `valid_at` on `add_triplet` when you already know when the claim became true.
Pass `now` on either ingest method to stamp transaction time.

## Search and look up

`search` embeds the query, fuses vector and full-text ranks, then expands one hop.
`valid_now` defaults to `True` and excludes expired facts.

```python
hits = await graph.search("where does Ada work?")
past = await graph.search("where does Ada work?", valid_now=False)
entity = await graph.get_entity(hits.entities[0].uuid)
fact = await graph.get_fact(hits.facts[0].uuid)
```

`get_entity` and `get_fact` return the stored record or `None`.

## Closed types

`Episode`, `Entity`, `Fact`, `Mention`, `IngestResult`, and `SearchHits` have closed field sets.
Do not subclass them.
`Entity.attributes` is an untyped `dict`.

## Models

Extract, resolve, and invalidate default to `google:gemini-3.7-flash`.
The embedder defaults to `google:gemini-embedding-2`.
Pass a `ModelStack` to override any of those.

```python
from zeit import Graph, ModelStack, PydanticAIEmbedder

graph = Graph(
    url,
    namespace,
    database,
    credentials,
    models=ModelStack(
        extract="google:gemini-3.7-flash",
        embedder=PydanticAIEmbedder("google:gemini-embedding-2"),
    ),
)
```

A custom embedder implements `async def embed(self, texts: list[str]) -> list[list[float]]`.

## Agent rules

Use `Graph.add_episode`, `add_triplet`, `search`, `get_entity`, and `get_fact`.
zeit is the ingest then resolve then expire then search algorithm.
SurrealDB, PydanticAI, and Logfire are how it runs, not what it is.
