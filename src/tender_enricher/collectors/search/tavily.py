from tender_enricher.collectors.search.http_provider import JsonSearchProvider, result_urls, token


class TavilySearchProvider(JsonSearchProvider):
    def search(self, query: str, limit: int = 5) -> list[str]:
        key = token(self.settings.tavily_api_key)
        if not key or limit <= 0:
            return []
        limit = min(limit, 20)
        data = self.request(
            "POST",
            "https://api.tavily.com/search",
            headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
            json={
                "query": query,
                "max_results": limit,
                "search_depth": "basic",
                "auto_parameters": False,
                "include_answer": False,
                "include_raw_content": False,
            },
        )
        return result_urls(data, "results", "url", limit)
