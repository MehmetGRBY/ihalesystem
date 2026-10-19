"""Search all configured providers, merge fairly, and isolate provider failures."""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from itertools import zip_longest
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from tender_enricher.collectors.search.brave import BraveSearchProvider
from tender_enricher.collectors.search.http_provider import token
from tender_enricher.collectors.search.searxng import SearxngSearchProvider
from tender_enricher.collectors.search.serper import SerperSearchProvider
from tender_enricher.collectors.search.tavily import TavilySearchProvider
from tender_enricher.config import Settings
from tender_enricher.errors import CollectionError
from tender_enricher.models import Issue
from tender_enricher.ports import SearchProvider

LABELS = {"brave": "Brave", "serper": "Google (Serper)", "tavily": "Tavily", "searxng": "SearXNG"}
ENGINE_LABELS = {"brave": "Brave", "duckduckgo": "DuckDuckGo", "yahoo": "Yahoo"}


def search_provider_label(settings: Settings, name: str) -> str:
    label = LABELS[name]
    if name == "searxng" and settings.searxng_engines:
        engines = ", ".join(
            ENGINE_LABELS.get(engine, engine) for engine in settings.searxng_engines
        )
        label += f" ({engines})"
    return label


class ManagedSearchProvider(SearchProvider, Protocol):
    def close(self) -> None: ...


def configured_search_providers(settings: Settings) -> list[str]:
    configured = {
        "brave": bool(token(settings.brave_api_key)),
        "serper": bool(token(settings.serper_api_key)),
        "tavily": bool(token(settings.tavily_api_key)),
        "searxng": settings.searxng_url is not None,
    }
    return [name for name in settings.search_providers if configured[name]]


def clean_url(value: str) -> tuple[str, str] | None:
    try:
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            return None
        host = url.hostname.lower()
        netloc = ("[" + host + "]") if ":" in host else host
        if url.port and url.port != (443 if url.scheme == "https" else 80):
            netloc += ":" + str(url.port)
        query = urlencode(
            [
                (key, val)
                for key, val in parse_qsl(url.query, keep_blank_values=True)
                if not key.lower().startswith("utm_")
                and key.lower() not in {"gclid", "fbclid", "msclkid"}
            ]
        )
        cleaned = urlunsplit((url.scheme, netloc, url.path or "/", query, ""))
        identity = urlunsplit((url.scheme, netloc.removeprefix("www."), url.path or "/", query, ""))
        return cleaned, identity
    except ValueError:
        return None


class MultiSearchProvider:
    def __init__(self, providers: dict[str, ManagedSearchProvider]) -> None:
        if not providers:
            raise ValueError("At least one search provider is required")
        self.providers = providers
        self._lock = threading.RLock()
        self._failures: list[str] = []
        self._engine_failures: list[str] = []
        self._cache: OrderedDict[tuple[str, int], tuple[float, list[str]]] = OrderedDict()

    def search(self, query: str, limit: int = 5) -> list[str]:
        if limit <= 0 or not query.strip():
            return []
        limit = min(limit, 20)
        key = (query.strip(), limit)
        with self._lock:
            self._failures = []
            self._engine_failures = []
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < 600:
                self._cache.move_to_end(key)
                return list(cached[1])
            batches = []
            with ThreadPoolExecutor(max_workers=len(self.providers)) as executor:
                tasks = {
                    name: executor.submit(provider.search, key[0], limit)
                    for name, provider in self.providers.items()
                }
                for name, task in tasks.items():
                    try:
                        batches.append(task.result())
                    except Exception:
                        self._failures.append(name)
                    provider = self.providers[name]
                    if isinstance(provider, SearxngSearchProvider):
                        self._engine_failures.extend(provider.failed_engines)
            if len(self._failures) == len(self.providers):
                raise CollectionError("search_unavailable", "Configured search providers failed.")
            seen = set()
            urls = []
            for candidates in zip_longest(*batches):
                for value in candidates:
                    cleaned = clean_url(value) if isinstance(value, str) else None
                    if cleaned is None or cleaned[1] in seen:
                        continue
                    seen.add(cleaned[1])
                    urls.append(cleaned[0])
                    if len(urls) == limit:
                        break
                if len(urls) == limit:
                    break
            if not self._failures and not self._engine_failures:
                self._cache[key] = (time.monotonic(), list(urls))
                self._cache.move_to_end(key)
                while len(self._cache) > 128:
                    self._cache.popitem(last=False)
            return urls

    def take_issues(self, stage: str) -> list[Issue]:
        with self._lock:
            issues = [
                Issue(
                    stage=stage,
                    code="search_provider_failed",
                    provider=name,
                    message=f"{LABELS.get(name, name)} aramasına erişilemedi.",
                )
                for name in self._failures
            ]
            issues.extend(
                Issue(
                    stage=stage,
                    code="search_engine_failed",
                    provider=f"searxng:{name}",
                    message=f"SearXNG: {ENGINE_LABELS.get(name, name)} aramasına erişilemedi.",
                )
                for name in dict.fromkeys(self._engine_failures)
            )
            self._failures = []
            self._engine_failures = []
            return issues

    def close(self) -> None:
        for provider in self.providers.values():
            try:
                provider.close()
            except Exception:
                pass


def search_issues(search: SearchProvider, stage: str) -> list[Issue]:
    return search.take_issues(stage) if isinstance(search, MultiSearchProvider) else []


def build_search_provider(settings: Settings) -> MultiSearchProvider | None:
    providers: dict[str, ManagedSearchProvider] = {}
    constructors: dict[str, Callable[[Settings], ManagedSearchProvider]] = {
        "brave": BraveSearchProvider,
        "serper": SerperSearchProvider,
        "tavily": TavilySearchProvider,
        "searxng": SearxngSearchProvider,
    }
    for name in configured_search_providers(settings):
        providers[name] = constructors[name](settings)
    return MultiSearchProvider(providers) if providers else None
