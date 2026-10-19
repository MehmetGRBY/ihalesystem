import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError

from tender_enricher.models import Issue, TenderInput


class JsonInputAdapter:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> Iterable[TenderInput | Issue]:
        document = json.loads(self.path.read_text(encoding="utf-8"))
        records = document if isinstance(document, list) else [document]
        for index, record in enumerate(records):
            try:
                yield TenderInput.model_validate(record)
            except ValidationError:
                yield Issue(
                    stage="input",
                    code="invalid_record",
                    message=f"Record {index + 1} does not match the input schema.",
                )
