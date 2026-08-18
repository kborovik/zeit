"""Store protocol and SurrealDB implementation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol, cast, overload, runtime_checkable
from uuid import UUID

from surrealdb import AsyncSurreal, RecordID
from surrealdb.connections.async_embedded import AsyncEmbeddedSurrealConnection
from surrealdb.connections.async_http import AsyncHttpSurrealConnection
from surrealdb.connections.async_ws import AsyncWsSurrealConnection
from surrealdb.types import Value

from .types import Entity, Episode, Fact, Mention, SearchHits

type Persistable = Episode | Entity | Fact | Mention
type Client = (
    AsyncEmbeddedSurrealConnection
    | AsyncWsSurrealConnection
    | AsyncHttpSurrealConnection
)

SCHEMA = """
DEFINE TABLE OVERWRITE episode SCHEMAFULL;
DEFINE FIELD content ON episode TYPE string;
DEFINE FIELD created_at ON episode TYPE datetime;

DEFINE TABLE OVERWRITE entity SCHEMAFULL;
DEFINE FIELD name ON entity TYPE string;
DEFINE FIELD attributes ON entity TYPE object FLEXIBLE;
DEFINE FIELD created_at ON entity TYPE datetime;
DEFINE FIELD embedding ON entity TYPE option<array<float>>;

DEFINE TABLE OVERWRITE fact SCHEMAFULL;
DEFINE FIELD subject_id ON fact TYPE record<entity>;
DEFINE FIELD predicate ON fact TYPE string;
DEFINE FIELD object_id ON fact TYPE record<entity>;
DEFINE FIELD statement ON fact TYPE string;
DEFINE FIELD valid_at ON fact TYPE datetime;
DEFINE FIELD invalid_at ON fact TYPE option<datetime>;
DEFINE FIELD created_at ON fact TYPE datetime;
DEFINE FIELD expired_at ON fact TYPE option<datetime>;
DEFINE FIELD embedding ON fact TYPE option<array<float>>;

DEFINE TABLE OVERWRITE mention SCHEMAFULL;
DEFINE FIELD episode_id ON mention TYPE record<episode>;
DEFINE FIELD entity_id ON mention TYPE record<entity>;
DEFINE FIELD surface ON mention TYPE string;

DEFINE INDEX OVERWRITE episode_created_at ON episode FIELDS created_at;
DEFINE ANALYZER OVERWRITE zeit TOKENIZERS class, camel FILTERS lowercase, ascii;
DEFINE INDEX OVERWRITE fact_statement_ft ON fact FIELDS statement
    FULLTEXT ANALYZER zeit BM25;
DEFINE INDEX OVERWRITE entity_name_ft ON entity FIELDS name
    FULLTEXT ANALYZER zeit BM25;
"""

_TABLE: dict[type[Persistable], str] = {
    Episode: "episode",
    Entity: "entity",
    Fact: "fact",
    Mention: "mention",
}

_EMBEDDED_SCHEMES = frozenset(
    {"mem", "memory", "file", "surrealkv", "surrealkv+versioned"}
)
_RRF_K = 60
_SEARCH_LIMIT = 10


@runtime_checkable
class Store(Protocol):
    async def put(
        self, record: Persistable, *, embedding: list[float] | None = None
    ) -> None: ...

    async def get(self, kind: type[Persistable], uuid: UUID) -> Persistable | None: ...

    async def search(
        self, query: str, embedding: list[float], *, valid_now: bool = True
    ) -> SearchHits: ...

    async def expire(
        self, fact_id: UUID, *, invalid_at: datetime, expired_at: datetime
    ) -> None: ...


class SurrealStore:
    def __init__(
        self,
        url: str,
        namespace: str,
        database: str,
        credentials: Mapping[str, str] | None = None,
    ) -> None:
        self.namespace = namespace
        self.database = database
        self._url = url
        self._credentials = dict(credentials) if credentials is not None else None
        self._db: Client = AsyncSurreal(url)
        self._ready = False
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._ready:
            await self._db.close()
            self._ready = False

    async def put(
        self, record: Persistable, *, embedding: list[float] | None = None
    ) -> None:
        await self._ensure()
        table = _TABLE[type(record)]
        await self._db.upsert(_rid(table, record.uuid), _payload(record, embedding))

    @overload
    async def get(self, kind: type[Episode], uuid: UUID) -> Episode | None: ...
    @overload
    async def get(self, kind: type[Entity], uuid: UUID) -> Entity | None: ...
    @overload
    async def get(self, kind: type[Fact], uuid: UUID) -> Fact | None: ...
    @overload
    async def get(self, kind: type[Mention], uuid: UUID) -> Mention | None: ...

    async def get(self, kind: type[Persistable], uuid: UUID) -> Persistable | None:
        await self._ensure()
        table = _TABLE[kind]
        row = _one(await self._db.select(_rid(table, uuid)))
        if row is None:
            return None
        return _from_row(kind, row)

    async def search(
        self, query: str, embedding: list[float], *, valid_now: bool = True
    ) -> SearchHits:
        await self._ensure()
        fact_lists: list[list[Fact]] = []
        entity_lists: list[list[Entity]] = []
        if query:
            fact_lists.append(await self._search_facts_text(query, valid_now))
            entity_lists.append(await self._search_entities_text(query))
        if embedding:
            fact_lists.append(await self._search_facts_vector(embedding, valid_now))
            entity_lists.append(await self._search_entities_vector(embedding))
        return SearchHits(
            facts=tuple(_rrf(fact_lists)),
            entities=tuple(_rrf(entity_lists)),
        )

    async def expire(
        self, fact_id: UUID, *, invalid_at: datetime, expired_at: datetime
    ) -> None:
        await self._ensure()
        await self._db.query(
            "UPDATE $id SET invalid_at = $invalid_at, expired_at = $expired_at",
            _bind(
                {
                    "id": _rid("fact", fact_id),
                    "invalid_at": invalid_at,
                    "expired_at": expired_at,
                }
            ),
        )

    async def recent_episodes(self, limit: int) -> tuple[Episode, ...]:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        await self._ensure()
        if limit == 0:
            return ()
        result = await self._db.query(
            """
            SELECT * FROM episode
            ORDER BY created_at DESC
            LIMIT $limit
            """,
            _bind({"limit": limit}),
        )
        return tuple(reversed(_episodes(result)))

    async def entities_named(self, name: str) -> tuple[Entity, ...]:
        await self._ensure()
        result = await self._db.query(
            """
            SELECT * FROM entity
            WHERE name = $name
            ORDER BY created_at ASC
            """,
            _bind({"name": name}),
        )
        return tuple(_entities(result))

    async def open_facts(
        self, entity_ids: Sequence[UUID], *, valid_now: bool = True
    ) -> tuple[Fact, ...]:
        unique = list(dict.fromkeys(entity_ids))
        if not unique:
            return ()
        await self._ensure()
        result = await self._db.query(
            """
            SELECT * FROM fact
            WHERE ($valid_now = false OR expired_at = NONE)
              AND (subject_id IN $ids OR object_id IN $ids)
            ORDER BY created_at ASC
            """,
            _bind(
                {
                    "ids": [_rid("entity", item) for item in unique],
                    "valid_now": valid_now,
                }
            ),
        )
        return tuple(_facts(result))

    async def _ensure(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            await self._db.connect(self._url)
            if self._credentials is not None and not _is_embedded(self._url):
                await self._db.signin(cast(dict[str, Value], self._credentials))
            await self._db.use(self.namespace, self.database)
            raw = await self._db.query_raw(SCHEMA)
            _raise_if_schema_failed(raw)
            self._ready = True

    async def _search_facts_text(self, query: str, valid_now: bool) -> list[Fact]:
        result = await self._db.query(
            """
            SELECT *, search::score(1) AS score FROM fact
            WHERE statement @1@ $query
              AND ($valid_now = false OR expired_at = NONE)
            ORDER BY score DESC
            LIMIT $limit
            """,
            _bind({"query": query, "valid_now": valid_now, "limit": _SEARCH_LIMIT}),
        )
        return _facts(result)

    async def _search_entities_text(self, query: str) -> list[Entity]:
        result = await self._db.query(
            """
            SELECT *, search::score(1) AS score FROM entity
            WHERE name @1@ $query
            ORDER BY score DESC
            LIMIT $limit
            """,
            _bind({"query": query, "limit": _SEARCH_LIMIT}),
        )
        return _entities(result)

    async def _search_facts_vector(
        self, embedding: list[float], valid_now: bool
    ) -> list[Fact]:
        result = await self._db.query(
            """
            SELECT *, vector::similarity::cosine(embedding, $embedding) AS score
            FROM fact
            WHERE embedding != NONE
              AND ($valid_now = false OR expired_at = NONE)
            ORDER BY score DESC
            LIMIT $limit
            """,
            _bind(
                {
                    "embedding": embedding,
                    "valid_now": valid_now,
                    "limit": _SEARCH_LIMIT,
                }
            ),
        )
        return _facts(result)

    async def _search_entities_vector(self, embedding: list[float]) -> list[Entity]:
        result = await self._db.query(
            """
            SELECT *, vector::similarity::cosine(embedding, $embedding) AS score
            FROM entity
            WHERE embedding != NONE
            ORDER BY score DESC
            LIMIT $limit
            """,
            _bind({"embedding": embedding, "limit": _SEARCH_LIMIT}),
        )
        return _entities(result)


def _is_embedded(url: str) -> bool:
    return url.split(":", 1)[0] in _EMBEDDED_SCHEMES


def _rid(table: str, uuid: UUID) -> RecordID:
    return RecordID(table, uuid)


def _bind(values: Mapping[str, object]) -> dict[str, Value]:
    return cast(dict[str, Value], dict(values))


def _payload(record: Persistable, embedding: list[float] | None) -> dict[str, Value]:
    data: dict[str, object]
    match record:
        case Episode():
            data = {"content": record.content, "created_at": record.created_at}
        case Entity():
            data = {
                "name": record.name,
                "attributes": dict(record.attributes),
                "created_at": record.created_at,
            }
        case Fact():
            data = {
                "subject_id": _rid("entity", record.subject_id),
                "predicate": record.predicate,
                "object_id": _rid("entity", record.object_id),
                "statement": record.statement,
                "valid_at": record.valid_at,
                "created_at": record.created_at,
            }
            if record.invalid_at is not None:
                data["invalid_at"] = record.invalid_at
            if record.expired_at is not None:
                data["expired_at"] = record.expired_at
        case Mention():
            data = {
                "episode_id": _rid("episode", record.episode_id),
                "entity_id": _rid("entity", record.entity_id),
                "surface": record.surface,
            }
    if embedding is not None and isinstance(record, Entity | Fact):
        data["embedding"] = embedding
    return _bind(data)


def _from_row(kind: type[Persistable], row: Mapping[str, object]) -> Persistable:
    if kind is Episode:
        return _episode(row)
    if kind is Entity:
        return _entity(row)
    if kind is Fact:
        return _fact(row)
    if kind is Mention:
        return _mention(row)
    raise TypeError(f"unsupported store kind: {kind}")


def _episode(row: Mapping[str, object]) -> Episode:
    return Episode(
        uuid=_as_uuid(row["id"]),
        content=str(row["content"]),
        created_at=_as_datetime(row["created_at"]),
    )


def _entity(row: Mapping[str, object]) -> Entity:
    raw_attrs = row.get("attributes", {})
    attributes: dict[str, object] = {}
    if isinstance(raw_attrs, dict):
        typed = cast(dict[object, object], raw_attrs)
        attributes = {str(key): value for key, value in typed.items()}
    return Entity(
        uuid=_as_uuid(row["id"]),
        name=str(row["name"]),
        attributes=attributes,
        created_at=_as_datetime(row["created_at"]),
    )


def _fact(row: Mapping[str, object]) -> Fact:
    return Fact(
        uuid=_as_uuid(row["id"]),
        subject_id=_as_uuid(row["subject_id"]),
        predicate=str(row["predicate"]),
        object_id=_as_uuid(row["object_id"]),
        statement=str(row["statement"]),
        valid_at=_as_datetime(row["valid_at"]),
        invalid_at=_opt_datetime(row.get("invalid_at")),
        created_at=_as_datetime(row["created_at"]),
        expired_at=_opt_datetime(row.get("expired_at")),
    )


def _mention(row: Mapping[str, object]) -> Mention:
    return Mention(
        uuid=_as_uuid(row["id"]),
        episode_id=_as_uuid(row["episode_id"]),
        entity_id=_as_uuid(row["entity_id"]),
        surface=str(row["surface"]),
    )


def _episodes(result: object) -> list[Episode]:
    return [_episode(row) for row in _rows(result)]


def _facts(result: object) -> list[Fact]:
    return [_fact(row) for row in _rows(result)]


def _entities(result: object) -> list[Entity]:
    return [_entity(row) for row in _rows(result)]


def _rows(result: object) -> list[Mapping[str, object]]:
    if result is None:
        return []
    if isinstance(result, dict):
        return [cast(Mapping[str, object], result)]
    if isinstance(result, list):
        rows: list[Mapping[str, object]] = []
        for item in cast(list[object], result):
            if isinstance(item, dict):
                rows.append(cast(Mapping[str, object], item))
        return rows
    return []


def _one(result: object) -> Mapping[str, object] | None:
    rows = _rows(result)
    if not rows:
        return None
    return rows[0]


def _as_uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, RecordID):
        return _as_uuid(value.id)
    if isinstance(value, str):
        return UUID(value)
    raise TypeError(f"cannot coerce {type(value)!r} to UUID")


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    raise TypeError(f"cannot coerce {type(value)!r} to datetime")


def _opt_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return _as_datetime(value)


def _rrf[T: Persistable](rankings: list[list[T]], *, k: int = _RRF_K) -> list[T]:
    scores: dict[UUID, float] = {}
    first: dict[UUID, T] = {}
    for ranking in rankings:
        for rank, record in enumerate(ranking, start=1):
            scores[record.uuid] = scores.get(record.uuid, 0.0) + 1.0 / (k + rank)
            first.setdefault(record.uuid, record)
    return [
        first[uuid]
        for uuid in sorted(scores, key=lambda item: scores[item], reverse=True)
    ]


def _raise_if_schema_failed(raw: Mapping[str, object]) -> None:
    result = raw.get("result")
    if not isinstance(result, list):
        raise RuntimeError(f"schema apply failed: {raw}")
    for statement in cast(list[object], result):
        if not isinstance(statement, dict):
            raise RuntimeError(f"schema apply failed: {statement}")
        if cast(dict[object, object], statement).get("status") != "OK":
            raise RuntimeError(f"schema apply failed: {statement}")
