# zeit

## §G GOAL

implement bi-temporal ingest-resolve-invalidate-hybrid-search as Python ≥3.14 lib `zeit`

## §C CONSTRAINTS

- Python ≥3.14; public API async only
- PydanticAI every LLM call; dep `pydantic-ai-slim[google]` only; ! unused extras (CLI, openai, anthropic); library instruments PydanticAI so Logfire traces those calls; library ! own Logfire token; library ! call logfire.configure
- SurrealDB only store; official `surrealdb` async client; SurrealQL; no GraphDriver ABC
- uv env; ruff lint+fmt; basedpyright strict

## §I INTERFACES

- api: `Graph.add_episode` / `add_triplet` / `search` / `get_entity` / `get_fact` → `IngestResult` or `SearchHits` or `Entity` or `Fact`
- type: `Episode` | `Entity` | `Fact` | `Mention` | `IngestResult` | `SearchHits` — closed fields; no tenant key
- proto: `Embedder.embed(list[str])` → `list[list[float]]`; `Store` put/get/search/expire
- ctor: `Graph(url, namespace, database, credentials, ModelStack?, episode_window=3, max_concurrency)` — defaults extract/resolve/invalidate=`google:gemini-3.7-flash`, embedder=`google:gemini-embedding-2`
- pkg: `import zeit` from `src/zeit/`; PyPI `zeit-graph`; runtime dep `pydantic-ai-slim[google]` + `logfire`
- env: caller configures Logfire at process start; library instruments PydanticAI; caller ! need logfire.instrument_pydantic_ai; library ! own token; library ! call logfire.configure; default Gemini path reads `GEMINI_API_KEY`; e2e reads repo `.env` before start; `.env.example` names `GEMINI_API_KEY` + `LOGFIRE_TOKEN` + `SURREAL_URL`; e2e ! those keys after load; `SURREAL_URL` default `ws://127.0.0.1:8000/rpc`; empty → brew start; `.env` ! committed
- cmd: `uv` env; `ruff check`/`ruff format`; `basedpyright` strict; SurrealDB ≥3; `brew install surrealdb/tap/surreal`; unit store tests + e2e start brew `surreal`; `pytest -m e2e`; tag `v*` → check + build + GH Release + `uv publish` PyPI `zeit-graph`
- agents: AGENTS.md Logfire MCP recipe — after `pytest -m e2e` query `query_schema_reference` then `query_run` for PydanticAI spans in e2e window by service name harness set at process start; pytest ! query Logfire HTTP
- readme: README.md after pitch → LLM-agent how-to use zeit as lib; ctor Graph + add_episode/add_triplet/search/get_entity/get_fact; bi-temporal clocks; ModelStack?; Logfire caller-configure; GEMINI_API_KEY; SurrealDB one Graph = one (namespace, database); ! maintainer run/release/status

## §V INVARIANTS

V1: staged-pipeline — zeit is bi-temporal ingest-resolve-invalidate-search algorithm; SurrealDB, PydanticAI, Logfire are how it runs not what it is
V2: bi-temporal-fact — Fact `valid_at`/`invalid_at` = world time; `created_at`/`expired_at` = txn time; contradict → set `invalid_at`+`expired_at`; ! drop row
V3: database-tenant — one `Graph` = one SurrealDB `(namespace, database)`; Episode|Entity|Fact|Mention have no tenant field; other database invisible via public API
V4: closed-types — Episode, Entity, Fact, Mention field sets closed; `Entity.attributes` untyped dict; no caller entity/fact classes
V5: pydantic-ai-llm — every LLM call via PydanticAI `Agent`; default model `google:gemini-3.7-flash`
V6: embedder-swap — `Embedder.embed(texts)` → `list[list[float]]`; ship PydanticAI impl default `google:gemini-embedding-2`; caller may swap
V7: logfire-observe — library instruments PydanticAI so every LLM call appears in Logfire once caller configured; caller ! need logfire.instrument_pydantic_ai; library ! take token; library ! call logfire.configure
V8: surreal-only — official `surrealdb` async client; SurrealQL only; store + tests target SurrealDB ≥3; ! `mem://` 2.x engine; no driver ABC; no Neo4j/Falkor/Kuzu/Neptune
V9: hybrid-rrf — `Graph.search` = embed query + vector kNN + full-text + RRF + one-hop expand; `valid_now` default true excludes expired facts
V10: entity-merge — two surface forms of same entity in one database → one `Entity` uuid
V11: py314-async — Python ≥3.14; public API async only; uv env; ruff lint+fmt; basedpyright strict
V12: first-party-prompts — new PydanticAI output models + instructions
V13: window-bound — `episode_window` default 3; extract/resolve fan-out bounded by `max_concurrency`
V14: md-ospl — Markdown prose: one sentence per line; sentence ! wrap across lines; headings tables code-fences exempt

## §T TASKS

id|status|task|cites
T1|x|init `src/zeit` pyproject Python ≥3.14 uv ruff basedpyright|V11
T2|x|add closed types Episode Entity Fact Mention IngestResult SearchHits|V4
T3|x|add Embedder protocol + PydanticAI impl|V6
T4|x|add Store protocol + SurrealDB schema and impl|V3,V8
T5|x|add extract prompts + PydanticAI agents|V5,V12
T6|x|add context window fetch last N episodes|V13
T7|x|add resolve dedupe against existing graph|V10
T8|x|add invalidate: contradict then expire fact|V2
T9|x|add `Graph.add_episode` context extract resolve invalidate embed persist|V1
T10|x|add `Graph.add_triplet` skip Extract|V1
T11|x|add `Graph.search` hybrid RRF + one-hop + uuid getters|V9
T12|x|wire Logfire on PydanticAI calls; no token in Graph|V7
T13|x|test expire, entity merge, db tenant isolation, valid_now search|V2,V3,V9,V10
T14|x|sweep `*.md` one sentence per line; sentence ! wrap|V14
T15|x|set ModelStack defaults `google:gemini-3.7-flash` + `google:gemini-embedding-2`; ModelStack optional on Graph|V5,V6,I.ctor
T16|x|swap dep to `pydantic-ai-slim[google]`; drop unused extras|V5,I.env
T17|x|add e2e: brew `surreal` fixture + org-chart SyntheticWorld + live Gemini + process-start Logfire + AGENTS.md MCP recipe; pytest asserts graph only|V2,V7,V8,V9,V10,I.env,I.cmd,I.agents
T18|x|add `.env.example` + e2e read `.env` before start|I.env,V7
T19|x|swap unit store tests off `mem://` 2.x onto brew SurrealDB ≥3; schema FULLTEXT only; drop SEARCH fallback|V8,I.cmd
T20|x|library instrument PydanticAI so every LLM call emits Logfire span after caller configure; caller ! need instrument_pydantic_ai; ! token ! configure|V7,I.env,I.pkg
T21|x|add tag `v*` publish PyPI `zeit-graph` via trusted publishing|I.pkg,I.cmd
T22|x|rewrite README.md from `## Intended shape` inclusive → LLM-agent how-to use zeit; drop Run from this repo, Release, How it runs, Status|V2,V3,V7,I.api,I.ctor,I.env,I.readme

## §B BUGS

id|date|cause|fix
