import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from tender_enricher.models import EnrichmentResult


class JsonOutputAdapter:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, results: Sequence[EnrichmentResult]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                delete=False,
            ) as handle:
                temporary = handle.name
                json.dump(
                    [result.model_dump(mode="json") for result in results],
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
