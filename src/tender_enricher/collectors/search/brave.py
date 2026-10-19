import time
from collections.abc import Callable

import httpx

from tender_enricher.config import Settings
from tender_enricher.errors import CollectionError


class BraveSearchProvider:
    """URL discovery for one supplied tender/company; snippets are never evidence."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings, self.sleep = settings, sleep
        self.client = client or httpx.Client(
            timeout=settings.request_timeout_seconds, trust_env=False, follow_redirects=False
        )
        self._last_request = 0.0

    def close(self) -> None:
        self.client.close()

    def search(self, query: str, limit: int = 5) -> list[str]:
        if not self.settings.brave_api_key or not self.settings.brave_api_key.get_secret_value():
            return []
        self.sleep(
            max(0, self._last_request + self.settings.request_interval_seconds - time.monotonic())
        )
        self._last_request = time.monotonic()
        try:
            response = self.client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": min(limit, 20), "country": "TR", "search_lang": "tr"},
                headers={
                    "X-Subscription-Token": self.settings.brave_api_key.get_secret_value(),
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("web", {}).get("results", [])
            return [
                item["url"]
                for item in results
                if isinstance(item, dict)
                and isinstance(item.get("url"), str)
                and item["url"].startswith(("https://", "http://"))
            ][:limit]
        except (httpx.HTTPError, ValueError, AttributeError, TypeError) as error:
            raise CollectionError(
                "search_failed", "Search API failed; supplied source URLs still work."
            ) from error
