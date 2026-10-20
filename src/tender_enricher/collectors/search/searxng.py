from typing import Any

from tender_enricher.collectors.search.http_provider import JsonSearchProvider, result_urls
from tender_enricher.errors import CollectionError


class SearxngSearchProvider(JsonSearchProvider):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.failed_engines: list[str] = []
        self.engine_counts: dict[str, int] = {}

    def search(self, query: str, limit: int = 5) -> list[str]:
        self.failed_engines = []
        self.engine_counts = {}
        if self.settings.searxng_url is None or limit <= 0:
            return []
        endpoint = str(self.settings.searxng_url).rstrip("/")
        if not endpoint.endswith("/search"):
            endpoint += "/search"
        params = {"q": query, "format": "json", "language": "tr-TR", "categories": "general"}
        if self.settings.searxng_engines:
            params["engines"] = ",".join(self.settings.searxng_engines)
        data = self.request(
            "GET",
            endpoint,
            params=params,
        )
        rows = data.get("results", [])
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("engines"), list):
                    continue
                for name in set(e for e in row["engines"] if isinstance(e, str)):
                    if name in self.settings.searxng_engines:
                        self.engine_counts[name] = self.engine_counts.get(name, 0) + 1
        failures = data.get("unresponsive_engines", [])
        if isinstance(failures, list):
            for failure in failures:
                if isinstance(failure, list) and failure and isinstance(failure[0], str):
                    name = failure[0]
                    if name in self.settings.searxng_engines:
                        self.failed_engines.append(name)
            if failures and not data.get("results"):
                raise CollectionError("search_unavailable", "SearXNG engines could not search.")
        return result_urls(data, "results", "url", min(limit, 20))
