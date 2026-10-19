import json
import threading

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from tender_enricher.collectors.search.brave import BraveSearchProvider
from tender_enricher.collectors.search.multi import (
    MultiSearchProvider,
    build_search_provider,
    clean_url,
    configured_search_providers,
)
from tender_enricher.collectors.search.searxng import SearxngSearchProvider
from tender_enricher.collectors.search.serper import SerperSearchProvider
from tender_enricher.collectors.search.tavily import TavilySearchProvider
from tender_enricher.config import Settings
from tender_enricher.errors import CollectionError


def keys(settings):
    return settings.model_copy(
        update={
            "brave_api_key": SecretStr("private-brave-key"),
            "serper_api_key": SecretStr("private-serper-key"),
            "tavily_api_key": SecretStr("private-tavily-key"),
            "searxng_url": "http://127.0.0.1:8080/",
        }
    )


@pytest.mark.parametrize("kind", ["brave", "serper", "tavily", "searxng"])
def test_provider_request_and_url_only_contract(settings, kind):
    visited = []
    good = "https://company.example/contact"

    def handler(request):
        visited.append(request)
        if kind == "brave":
            assert request.headers["X-Subscription-Token"] == "private-brave-key"
            assert request.url.params["q"] == "Firma iletişim"
            return httpx.Response(
                200,
                json={
                    "web": {
                        "results": [
                            {"url": good, "description": "Not evidence"},
                            {"url": "file:///private"},
                        ]
                    }
                },
            )
        if kind == "serper":
            assert request.url == "https://google.serper.dev/search"
            assert request.headers["X-API-KEY"] == "private-serper-key"
            assert json.loads(request.content) == {
                "q": "Firma iletişim",
                "num": 10,
                "gl": "tr",
                "hl": "tr",
            }
            return httpx.Response(
                200,
                json={
                    "organic": [
                        {"link": good, "snippet": "Not evidence"},
                        {"link": "javascript:bad"},
                    ]
                },
            )
        if kind == "tavily":
            assert request.url == "https://api.tavily.com/search"
            assert request.headers["Authorization"] == "Bearer private-tavily-key"
            payload = json.loads(request.content)
            assert payload["include_answer"] is False and payload["include_raw_content"] is False
            assert payload["search_depth"] == "basic" and payload["max_results"] == 5
        else:
            assert str(request.url).startswith("http://127.0.0.1:8080/search?")
            assert request.url.params["format"] == "json"
            assert request.url.params["language"] == "tr-TR"
        return httpx.Response(200, json={"results": [{"url": good}, {"url": "data:bad"}]})

    constructor = {
        "brave": BraveSearchProvider,
        "serper": SerperSearchProvider,
        "tavily": TavilySearchProvider,
        "searxng": SearxngSearchProvider,
    }[kind]
    provider = constructor(
        keys(settings),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    try:
        assert provider.search("Firma iletişim") == [good]
        assert provider.search("Firma iletişim", limit=0) == []
        assert len(visited) == 1
    finally:
        provider.close()


@pytest.mark.parametrize(
    "constructor",
    [BraveSearchProvider, SerperSearchProvider, TavilySearchProvider, SearxngSearchProvider],
)
def test_disabled_provider_never_calls_network(settings, constructor):
    provider = constructor(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("Network called"))),
    )
    try:
        assert provider.search("q") == []
    finally:
        provider.close()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429, text="private-serper-key"),
        httpx.Response(200, json={"error": "private-serper-key"}),
        httpx.Response(200, json={"organic": None}),
        httpx.Response(200, json=[]),
    ],
)
def test_provider_errors_are_safe_and_reported(settings, response):
    provider = SerperSearchProvider(
        keys(settings),
        client=httpx.Client(transport=httpx.MockTransport(lambda _: response)),
        sleep=lambda _: None,
    )
    try:
        with pytest.raises(CollectionError) as failure:
            provider.search("q")
        assert "private" not in str(failure.value)
        assert failure.value.code == "search_failed"
    finally:
        provider.close()


class Provider:
    def __init__(self, urls=(), fail=False, barrier=None):
        self.urls, self.fail, self.barrier = list(urls), fail, barrier
        self.calls = 0
        self.closed = False

    def search(self, query, limit=5):
        self.calls += 1
        if self.barrier:
            self.barrier.wait(timeout=3)
        if self.fail:
            raise RuntimeError("private-key-must-not-escape")
        return self.urls[:limit]

    def close(self):
        self.closed = True


def test_all_sources_participate_in_parallel_and_results_are_mixed():
    barrier = threading.Barrier(3)
    providers = {
        name: Provider([f"https://{name}.example/{i}" for i in range(5)], barrier=barrier)
        for name in ["brave", "serper", "tavily"]
    }
    group = MultiSearchProvider(providers)
    assert group.search("q", limit=5) == [
        "https://brave.example/0",
        "https://serper.example/0",
        "https://tavily.example/0",
        "https://brave.example/1",
        "https://serper.example/1",
    ]
    group.close()
    assert all(provider.calls == 1 and provider.closed for provider in providers.values())


def test_failed_source_does_not_hide_other_results_or_cache_partial_failure():
    bad, good = Provider(fail=True), Provider(["https://good.example/"])
    group = MultiSearchProvider({"brave": bad, "tavily": good})
    assert group.search("q") == ["https://good.example/"]
    issues = group.take_issues("enrichment")
    assert len(issues) == 1 and issues[0].provider == "brave"
    assert "private" not in issues[0].message
    assert group.take_issues("enrichment") == []
    assert group.search("q") == ["https://good.example/"]
    assert good.calls == bad.calls == 2


def test_all_provider_failures_are_explicit():
    group = MultiSearchProvider({"brave": Provider(fail=True), "serper": Provider(fail=True)})
    with pytest.raises(CollectionError) as failure:
        group.search("q")
    assert failure.value.code == "search_unavailable"
    assert {issue.provider for issue in group.take_issues("search")} == {"brave", "serper"}


def test_duplicate_search_urls_do_not_become_multiple_sources():
    group = MultiSearchProvider(
        {
            "brave": Provider(
                ["https://www.abc.com/contact?utm_source=brave#top", "https://abc.com/project?id=1"]
            ),
            "serper": Provider(
                ["https://abc.com/contact?fbclid=tracking", "https://abc.com/project?id=2"]
            ),
        }
    )
    assert group.search("q") == [
        "https://www.abc.com/contact",
        "https://abc.com/project?id=1",
        "https://abc.com/project?id=2",
    ]


def test_successful_query_cache_and_zero_limit_do_not_spend_extra_calls():
    provider = Provider(["https://abc.com/"])
    group = MultiSearchProvider({"brave": provider})
    assert group.search(" q ") == group.search("q") == ["https://abc.com/"]
    assert group.search("q", 0) == group.search("   ") == []
    assert provider.calls == 1


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "https://user:password@abc.com/", "http://abc.com:bad/", "not a URL"],
)
def test_unsafe_result_urls_are_discarded(url):
    assert clean_url(url) is None


def test_factory_enables_all_configured_and_selected_sources(settings):
    configured = keys(settings).model_copy(update={"search_providers": ["tavily", "serper"]})
    assert configured_search_providers(configured) == ["tavily", "serper"]
    group = build_search_provider(configured)
    try:
        assert list(group.providers) == ["tavily", "serper"]
    finally:
        group.close()
    assert build_search_provider(settings) is None


@pytest.mark.parametrize(
    "extra",
    [
        {"search_providers": ["unknown"]},
        {"search_providers": ["brave", "brave"]},
        {"searxng_url": "http://user:secret@localhost:8080"},
        {"searxng_url": "http://localhost:8080/?key=secret"},
    ],
)
def test_search_settings_validation(extra):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **extra)


def test_provider_timeout_is_a_safe_search_failure(settings):
    def timeout(request):
        raise httpx.ReadTimeout("private-serper-key", request=request)

    provider = SerperSearchProvider(
        keys(settings),
        client=httpx.Client(transport=httpx.MockTransport(timeout)),
        sleep=lambda _: None,
    )
    try:
        with pytest.raises(CollectionError) as failure:
            provider.search("q")
        assert failure.value.code == "search_failed"
        assert "private" not in str(failure.value)
    finally:
        provider.close()


@pytest.mark.parametrize("all_failed", [False, True])
def test_pipeline_keeps_supplied_sources_and_exposes_engine_failures(
    settings, repository, all_failed
):
    from pathlib import Path

    from tender_enricher.collectors.company_website.website import CompanyWebsiteCollector
    from tender_enricher.collectors.demo import DemoFetcher
    from tender_enricher.collectors.ekap.award import PublicAwardCollector
    from tender_enricher.collectors.trade_registry.registry import PublicRegistryCollector
    from tender_enricher.models import TenderInput
    from tender_enricher.pipeline import Pipeline

    root = Path(__file__).resolve().parents[1]
    record = TenderInput.model_validate(
        json.loads((root / "data/demo/tenders.json").read_text())[0]
    )
    award_url = str(record.award_urls[0])
    search = MultiSearchProvider(
        {
            "brave": Provider(fail=True),
            "serper": Provider([award_url], fail=all_failed),
            "tavily": Provider([award_url], fail=all_failed),
        }
    )
    fetcher = DemoFetcher(root / "data/demo")
    result = Pipeline(
        [PublicAwardCollector(fetcher, settings, search)],
        [
            CompanyWebsiteCollector(fetcher, settings, search),
            PublicRegistryCollector(fetcher, settings),
        ],
        repository,
        is_demo=True,
    ).process(record)
    assert result.status == "resolved"
    assert result.winner.company_name.startswith("ABC")
    assert any(
        issue.code == "search_provider_failed" and issue.provider == "brave"
        for issue in result.issues
    )
    assert (
        sum(
            str(source.url) == award_url and source.source_type == "official_award"
            for source in result.sources
        )
        == 1
    )
    assert all(str(source.url).endswith(("/2026-123456", "/", "/abc")) for source in result.sources)


def test_searxng_empty_value_and_local_operator_endpoint():
    assert Settings(_env_file=None, searxng_url="").searxng_url is None
    assert (
        str(Settings(_env_file=None, searxng_url="http://localhost:8080").searxng_url)
        == "http://localhost:8080/"
    )
