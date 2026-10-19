"""Small authenticated search clients. Search snippets are never company evidence."""

import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import SecretStr

from tender_enricher.config import Settings
from tender_enricher.errors import CollectionError


class JsonSearchProvider:
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
        self._lock = threading.Lock()

    def close(self) -> None:
        self.client.close()

    def request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        with self._lock:
            self.sleep(
                max(
                    0,
                    self._last_request + self.settings.request_interval_seconds - time.monotonic(),
                )
            )
            self._last_request = time.monotonic()
            try:
                response = self.client.request(method, url, **kwargs)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or data.get("error"):
                    raise ValueError("Invalid search response")
                return data
            except (httpx.HTTPError, ValueError, TypeError) as error:
                raise CollectionError(
                    "search_failed", "Search provider could not complete the request."
                ) from error


def token(value: SecretStr | None) -> str:
    return value.get_secret_value().strip() if value else ""


def result_urls(data: dict[str, Any], field: str, url_field: str, limit: int) -> list[str]:
    results = data.get(field, [])
    if not isinstance(results, list):
        raise CollectionError("search_failed", "Search provider returned an invalid results list.")
    return [
        item[url_field]
        for item in results
        if isinstance(item, dict)
        and isinstance(item.get(url_field), str)
        and item[url_field].startswith(("https://", "http://"))
    ][:limit]
