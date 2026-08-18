"""Org-chart SyntheticWorld used by the live e2e suite."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from zeit import Graph, IngestResult

E2E_SERVICE_NAME = "zeit-e2e"
E2E_NAMESPACE = "zeit"


@dataclass(frozen=True, slots=True)
class WorldEpisode:
    content: str
    now: datetime


class SyntheticWorld:
    """Org-chart world ingested as episodes for e2e."""

    ada = "Ada Lovelace"
    ada_alias = "Ada"
    bob = "Bob Martinez"
    cara = "Cara Chen"
    dana = "Dana Okonkwo"
    acme = "Acme"
    birch = "Birch"
    jan = datetime(2026, 1, 15, tzinfo=UTC)
    feb = datetime(2026, 2, 15, tzinfo=UTC)
    march = datetime(2026, 3, 1, tzinfo=UTC)
    april = datetime(2026, 4, 1, tzinfo=UTC)

    def episodes(self) -> tuple[WorldEpisode, ...]:
        return (
            WorldEpisode(
                content=(
                    f"{self.ada} is the VP of Engineering at {self.acme}. "
                    f"{self.bob} reports to {self.ada}. "
                    f"{self.cara} reports to {self.ada}."
                ),
                now=self.jan,
            ),
            WorldEpisode(
                content=(
                    f"{self.dana} joined {self.acme} as a designer. "
                    f"{self.dana} reports to {self.cara}."
                ),
                now=self.feb,
            ),
            WorldEpisode(
                content=(
                    f"{self.ada} left {self.acme} for {self.birch} in March. "
                    f"{self.ada} now works at {self.birch}. "
                    f"{self.bob} now reports to {self.cara} instead of {self.ada}."
                ),
                now=self.april,
            ),
            WorldEpisode(
                content=(
                    f"{self.ada_alias} now leads the platform team at {self.birch}. "
                    f"{self.ada_alias} is the same person as {self.ada}."
                ),
                now=self.april,
            ),
        )


@dataclass(frozen=True, slots=True)
class IngestedWorld:
    graph: Graph
    world: SyntheticWorld
    results: tuple[IngestResult, ...]
