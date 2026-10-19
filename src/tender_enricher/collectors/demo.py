import json
from pathlib import Path

from tender_enricher.collectors.web import Document
from tender_enricher.errors import CollectionError


class DemoFetcher:
    """Explicit offline mode. Synthetic pages can never become live HTTP fallbacks."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.manifest: dict[str, str] = json.loads(
            (directory / "manifest.json").read_text(encoding="utf-8")
        )

    def begin_tender(self) -> None:
        pass

    def close(self) -> None:
        pass

    def fetch(self, url: str) -> Document:
        filename = self.manifest.get(url)
        if filename is None:
            raise CollectionError(
                "demo_page_missing", "URL is absent from the offline demo manifest."
            )
        path = (self.directory / filename).resolve()
        if not path.is_relative_to(self.directory):
            raise CollectionError(
                "unsafe_demo_path", "Demo page must be inside the demo directory."
            )
        return Document(url, url, path.read_text(encoding="utf-8"), is_demo=True)
