from typing import Protocol

from tender_enricher.collectors.web import Document


class PageFetcher(Protocol):
    def fetch(self, url: str) -> Document: ...

    def begin_tender(self) -> None: ...

    def close(self) -> None: ...
