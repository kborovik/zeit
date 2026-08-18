# zeit

## §G GOAL

implement bi-temporal ingest-resolve-invalidate-hybrid-search as Python ≥3.14 lib `zeit`

## §C CONSTRAINTS

- Python ≥3.14; public API async only
- PydanticAI every LLM call; Logfire traces those calls; library ! own Logfire token
- SurrealDB only store; official `surrealdb` async client; SurrealQL; no GraphDriver ABC
- uv env; ruff lint+fmt; basedpyright strict

## §I INTERFACES

- api: `Graph.add_episode` / `add_triplet` / `search` / `get_entity` / `get_fact` → `IngestResult` or `SearchHits` or `Entity` or `Fact`
- type: `Episode` | `Entity` | `Fact` | `Mention` | `IngestResult` | `SearchHits` — closed fields; no tenant key
- proto: `Embedder.embed(list[str])` → `list[list[float]]`; `Store` put/get/search/expire
- ctor: `Graph(url, namespace, database, credentials, ModelStack, episode_window=3, max_concurrency)`
- pkg: `import zeit` from `src/zeit/`
- env: caller configures Logfire at process start; library ! own token
- cmd: `uv` env; `ruff check`/`ruff format`; `basedpyright` strict

## §V INVARIANTS

V1: staged-pipeline — zeit is bi-temporal ingest-resolve-invalidate-search algorithm; SurrealDB, PydanticAI, Logfire are how it runs not what it is
V2: bi-temporal-fact — Fact `valid_at`/`invalid_at` = world time; `created_at`/`expired_at` = txn time; contradict → set `invalid_at`+`expired_at`; ! drop row
V3: database-tenant — one `Graph` = one SurrealDB `(namespace, database)`; Episode|Entity|Fact|Mention have no tenant field; other database invisible via public API
V4: closed-types — Episode, Entity, Fact, Mention field sets closed; `Entity.attributes` untyped dict; no caller entity/fact classes
V5: pydantic-ai-llm — every LLM call via PydanticAI `Agent`
V6: embedder-swap — `Embedder.embed(texts)` → `list[list[float]]`; ship PydanticAI impl; caller may swap
V7: logfire-observe — PydanticAI calls appear in Logfire; library ! take Logfire token
V8: surreal-only — official `surrealdb` async client; SurrealQL only; no driver ABC; no Neo4j/Falkor/Kuzu/Neptune
V9: hybrid-rrf — `Graph.search` = embed query + vector kNN + full-text + RRF + one-hop expand; `valid_now` default true excludes expired facts
V10: entity-merge — two surface forms of same entity in one database → one `Entity` uuid
V11: py314-async — Python ≥3.14; public API async only; uv env; ruff lint+fmt; basedpyright strict
V12: first-party-prompts — new PydanticAI output models + instructions
V13: window-bound — `episode_window` default 3; extract/resolve fan-out bounded by `max_concurrency`
V14: md-ospl — Markdown prose: one sentence per line; sentence ! wrap across lines; headings tables code-fences exempt

## §T TASKS

id|status|task|cites
T1|x|init `src/zeit` pyproject Python ≥3.14 uv ruff basedpyright|V11
T2|.|add closed types Episode Entity Fact Mention IngestResult SearchHits|V4
T3|.|add Embedder protocol + PydanticAI impl|V6
T4|.|add Store protocol + SurrealDB schema and impl|V3,V8
T5|.|add extract prompts + PydanticAI agents|V5,V12
T6|.|add context window fetch last N episodes|V13
T7|.|add resolve dedupe against existing graph|V10
T8|.|add invalidate: contradict then expire fact|V2
T9|.|add `Graph.add_episode` context extract resolve invalidate embed persist|V1
T10|.|add `Graph.add_triplet` skip Extract|V1
T11|.|add `Graph.search` hybrid RRF + one-hop + uuid getters|V9
T12|.|wire Logfire on PydanticAI calls; no token in Graph|V7
T13|.|test expire, entity merge, db tenant isolation, valid_now search|V2,V3,V9,V10
T14|x|sweep `*.md` one sentence per line; sentence ! wrap|V14

## §B BUGS

id|date|cause|fix
