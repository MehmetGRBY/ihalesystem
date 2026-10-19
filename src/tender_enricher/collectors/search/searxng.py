from tender_enricher.collectors.search.http_provider import JsonSearchProvider, result_urls


class SearxngSearchProvider(JsonSearchProvider):
    def search(self, query: str, limit: int = 5) -> list[str]:
        if self.settings.searxng_url is None or limit <= 0:
            return []
        endpoint = str(self.settings.searxng_url).rstrip("/")
        if not endpoint.endswith("/search"):
            endpoint += "/search"
        data = self.request(
            "GET",
            endpoint,
            params={"q": query, "format": "json", "language": "tr-TR", "categories": "general"},
        )
        return result_urls(data, "results", "url", min(limit, 20))
