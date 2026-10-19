from tender_enricher.collectors.search.http_provider import JsonSearchProvider, result_urls, token


class SerperSearchProvider(JsonSearchProvider):
    def search(self, query: str, limit: int = 5) -> list[str]:
        key = token(self.settings.serper_api_key)
        if not key or limit <= 0:
            return []
        limit = min(limit, 20)
        data = self.request(
            "POST",
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Accept": "application/json"},
            json={"q": query, "num": max(10, limit), "gl": "tr", "hl": "tr"},
        )
        return result_urls(data, "organic", "link", limit)
