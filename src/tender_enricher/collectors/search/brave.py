from tender_enricher.collectors.search.http_provider import JsonSearchProvider, result_urls, token
from tender_enricher.errors import CollectionError


class BraveSearchProvider(JsonSearchProvider):
    """URL discovery only; search snippets are never company evidence."""

    def search(self, query: str, limit: int = 5) -> list[str]:
        key = token(self.settings.brave_api_key)
        if not key or limit <= 0:
            return []
        limit = min(limit, 20)
        data = self.request(
            "GET",
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": limit, "country": "TR", "search_lang": "tr"},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
        )
        web = data.get("web", {})
        if not isinstance(web, dict):
            raise CollectionError("search_failed", "Search provider returned invalid web results.")
        return result_urls(web, "results", "url", limit)
