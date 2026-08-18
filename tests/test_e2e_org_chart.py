from collections.abc import Iterable
from uuid import UUID

import pytest

from e2e_world import IngestedWorld, SyntheticWorld
from zeit import Entity, Fact, SearchHits

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.asyncio(loop_scope="module"),
]


def _fold(name: str) -> str:
    return " ".join(name.casefold().split())


def _canon(world: SyntheticWorld, name: str) -> str | None:
    folded = _fold(name)
    aliases = {
        _fold(world.ada): "ada",
        _fold(world.ada_alias): "ada",
        _fold(world.bob): "bob",
        "bob": "bob",
        _fold(world.cara): "cara",
        "cara": "cara",
        _fold(world.dana): "dana",
        "dana": "dana",
        _fold(world.acme): "acme",
        _fold(world.birch): "birch",
    }
    if folded in aliases:
        return aliases[folded]
    for alias, canon in aliases.items():
        if alias and (alias in folded or folded in alias):
            return canon
    return None


def _entities(ingested: IngestedWorld) -> tuple[Entity, ...]:
    seen: dict[UUID, Entity] = {}
    for result in ingested.results:
        for entity in result.entities:
            seen[entity.uuid] = entity
    return tuple(seen.values())


def _named(ingested: IngestedWorld, canon: str) -> tuple[Entity, ...]:
    return tuple(
        entity
        for entity in _entities(ingested)
        if _canon(ingested.world, entity.name) == canon
    )


def _ids(records: Iterable[Entity] | Iterable[Fact]) -> set[UUID]:
    return {record.uuid for record in records}


def _links(
    fact: Fact,
    by_id: dict[UUID, Entity],
    world: SyntheticWorld,
    subject: str,
    obj: str,
) -> bool:
    left = by_id.get(fact.subject_id)
    right = by_id.get(fact.object_id)
    if left is None or right is None:
        return False
    return _canon(world, left.name) == subject and _canon(world, right.name) == obj


def _job(ingested: IngestedWorld, company: str) -> Fact | None:
    by_id = {entity.uuid: entity for entity in _entities(ingested)}
    for result in ingested.results:
        for fact in result.facts:
            if _links(fact, by_id, ingested.world, "ada", company):
                return fact
    token = company
    for result in ingested.results:
        for fact in result.facts:
            text = fact.statement.casefold()
            if token in text and any(
                word in text for word in ("work", "vp", "engineer", "joined", "left")
            ):
                return fact
    return None


async def test_contradiction_expires_fact_without_drop(ingested: IngestedWorld) -> None:
    acme = _job(ingested, "acme")
    birch = _job(ingested, "birch")
    assert acme is not None
    assert birch is not None
    stored = await ingested.graph.get_fact(acme.uuid)
    assert stored is not None
    assert stored.uuid == acme.uuid
    assert stored.statement == acme.statement
    assert stored.invalid_at is not None
    assert stored.expired_at is not None
    current = await ingested.graph.get_fact(birch.uuid)
    assert current is not None
    assert current.invalid_at is None
    assert current.expired_at is None


async def test_alias_surface_merges_to_one_entity_uuid(ingested: IngestedWorld) -> None:
    ada = _named(ingested, "ada")
    assert ada
    assert len({entity.uuid for entity in ada}) == 1
    stored = await ingested.graph.get_entity(ada[0].uuid)
    assert stored is not None
    assert stored.uuid == ada[0].uuid
    surfaces = {
        mention.surface
        for result in ingested.results
        for mention in result.mentions
        if mention.entity_id == ada[0].uuid
    }
    folded = {_fold(item) for item in surfaces}
    assert (
        _fold(ingested.world.ada) in folded or _fold(ingested.world.ada_alias) in folded
    )


async def test_search_valid_now_excludes_expired(ingested: IngestedWorld) -> None:
    acme = _job(ingested, "acme")
    birch = _job(ingested, "birch")
    assert acme is not None
    assert birch is not None
    hits = await ingested.graph.search("where does Ada work")
    assert isinstance(hits, SearchHits)
    assert birch.uuid in _ids(hits.facts)
    assert acme.uuid not in _ids(hits.facts)
    history = await ingested.graph.search("where does Ada work", valid_now=False)
    assert birch.uuid in _ids(history.facts)
    assert acme.uuid in _ids(history.facts)


async def test_search_uses_live_surreal_server(
    ingested: IngestedWorld, surreal_url: str
) -> None:
    assert ingested.graph.store.namespace == "zeit"
    assert ingested.graph.store.database.startswith("e2e_")
    assert surreal_url.startswith(("ws://", "wss://", "http://", "https://"))
    assert not surreal_url.startswith("mem")
    hits = await ingested.graph.search("Cara Chen")
    assert hits.facts or hits.entities
    cara = _named(ingested, "cara")
    assert cara
    assert await ingested.graph.get_entity(cara[0].uuid) == cara[0]
