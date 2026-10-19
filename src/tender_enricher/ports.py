"""Interfaces for boundaries that the real tender system will replace."""

from collections.abc import Iterable, Sequence
from typing import Protocol

from tender_enricher.models import (
    Collection,
    CompanyProfile,
    EnrichmentResult,
    Issue,
    NormalizedTender,
    TenderInput,
)


class InputAdapter(Protocol):
    def read(self) -> Iterable[TenderInput | Issue]: ...


class OutputAdapter(Protocol):
    def write(self, results: Sequence[EnrichmentResult]) -> None: ...


class WinnerProvider(Protocol):
    name: str

    def collect(self, tender: NormalizedTender) -> Collection: ...


class CompanyProvider(Protocol):
    name: str

    def collect(self, tender: NormalizedTender, winner: CompanyProfile) -> Collection: ...


class ResultRepository(Protocol):
    def save(self, tender: NormalizedTender, result: EnrichmentResult) -> None: ...

    def latest(self, tender_id: str) -> EnrichmentResult | None: ...


class SearchProvider(Protocol):
    def search(self, query: str, limit: int = 5) -> list[str]: ...
