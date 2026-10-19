import socket
from unittest.mock import Mock

import httpx
import pytest
from pydantic import SecretStr

from tender_enricher.collectors.browser import BrowserClient
from tender_enricher.collectors.search.brave import BraveSearchProvider
from tender_enricher.collectors.web import WebClient, public_url
from tender_enricher.errors import CollectionError


class Clock:
    def __init__(self):
        self.value = 0.0
        self.waits = []

    def sleep(self, delay):
        self.waits.append(delay)
        self.value += delay

    def now(self):
        return self.value


def web(settings, handler, clock=None, validate=None):
    clock = clock or Clock()
    return WebClient(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=clock.sleep,
        clock=clock.now,
        validate_url=validate or (lambda url: None),
    )


def html(body="<p>Public page</p>"):
    return httpx.Response(200, text=body, headers={"Content-Type": "text/html; charset=utf-8"})


def test_robots_denial_stops_before_page_request(settings):
    visited = []

    def handler(request):
        visited.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow: /private")

    with pytest.raises(CollectionError, match="disallows"):
        web(settings, handler).fetch("https://a.com/private")
    assert visited == ["/robots.txt"]


def test_missing_robots_allows_but_unavailable_robots_fails_closed(settings):
    for status, expected in [(404, True), (502, False)]:

        def handler(request, status=status):
            return httpx.Response(status) if request.url.path == "/robots.txt" else html()

        client = web(settings, handler)
        if expected:
            assert "Public page" in client.fetch("https://a.com/page").body
        else:
            with pytest.raises(CollectionError):
                client.fetch("https://a.com/page")


def test_host_rate_limit_respects_robot_crawl_delay(settings):
    clock = Clock()
    requested_at = []

    def handler(request):
        requested_at.append(clock.now())
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nCrawl-delay: 5")
        return html()

    client = web(settings, handler, clock)
    client.fetch("https://a.com/one")
    client.fetch("https://a.com/two")
    assert requested_at == [0, 5, 10]


def test_retry_after_and_bounded_retry(settings):
    clock, calls = Clock(), []

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(clock.now())
        return httpx.Response(429, headers={"Retry-After": "7"}) if len(calls) == 1 else html()

    assert web(settings, handler, clock).fetch("https://a.com/page").body
    assert calls[1] - calls[0] >= 7


def test_retry_exhaustion(settings):
    attempts = []

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        attempts.append(request.url)
        return httpx.Response(503)

    with pytest.raises(CollectionError) as failure:
        web(settings, handler).fetch("https://a.com/page")
    assert failure.value.code == "retry_exhausted"
    assert len(attempts) == settings.max_attempts


def test_long_retry_after_defers_without_early_retry(settings):
    attempts = []

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        attempts.append(1)
        return httpx.Response(429, headers={"Retry-After": "3600"})

    with pytest.raises(CollectionError) as failure:
        web(settings, handler).fetch("https://a.com/page")
    assert failure.value.code == "retry_deferred"
    assert len(attempts) == 1


@pytest.mark.parametrize(
    "status,body", [(403, "forbidden"), (200, "<div class='hcaptcha'>challenge</div>")]
)
def test_protected_access_is_not_retried_or_bypassed(settings, status, body):
    visited = []

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        visited.append(request.url)
        return httpx.Response(status, text=body, headers={"Content-Type": "text/html"})

    with pytest.raises(CollectionError):
        web(settings, handler).fetch("https://a.com/page")
    assert len(visited) == 1


def test_redirect_policy_blocks_private_target(settings):
    visited = []

    def validate(url):
        if "127.0.0.1" in url:
            raise CollectionError("unsafe_url", "Private target blocked")

    def handler(request):
        visited.append(str(request.url))
        return (
            httpx.Response(404)
            if request.url.path == "/robots.txt"
            else httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"})
        )

    with pytest.raises(CollectionError) as failure:
        web(settings, handler, validate=validate).fetch("https://a.com/page")
    assert failure.value.code == "unsafe_url"
    assert not any("127.0.0.1" in url for url in visited)


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "192.0.2.1"]
)
def test_public_url_rejects_private_reserved_addresses(monkeypatch, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))],
    )
    with pytest.raises(CollectionError) as failure:
        public_url("https://untrusted.example/page")
    assert failure.value.code == "unsafe_url"


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "https://user:pass@a.com", "http://a.com:8080/"]
)
def test_public_url_rejects_credentials_schemes_and_ports(url):
    with pytest.raises(CollectionError):
        public_url(url)


def test_cache_and_page_budget(settings):
    settings = settings.model_copy(update={"max_pages_per_tender": 1})
    client = web(
        settings,
        lambda request: httpx.Response(404) if request.url.path == "/robots.txt" else html(),
    )
    first = client.fetch("https://a.com/one")
    assert client.fetch("https://a.com/one") is first
    with pytest.raises(CollectionError) as failure:
        client.fetch("https://a.com/two")
    assert failure.value.code == "page_budget_exceeded"
    client.begin_tender()
    assert client.fetch("https://a.com/two")


def test_page_size_and_content_type_limits(settings):
    settings = settings.model_copy(update={"max_response_bytes": 1024})
    for response in (
        html("x" * 1025),
        httpx.Response(200, content=b"pdf", headers={"Content-Type": "application/pdf"}),
    ):
        client = web(
            settings,
            lambda request, response=response: (
                httpx.Response(404) if request.url.path == "/robots.txt" else response
            ),
        )
        with pytest.raises(CollectionError):
            client.fetch("https://a.com/page")


def test_browser_stops_on_http_protection_before_launch(settings, monkeypatch):
    launch = Mock()
    monkeypatch.setattr("tender_enricher.collectors.browser.sync_playwright", launch)
    client = web(
        settings,
        lambda request: (
            httpx.Response(404) if request.url.path == "/robots.txt" else html("hcaptcha")
        ),
    )
    with pytest.raises(CollectionError):
        BrowserClient(client).fetch("https://a.com/page")
    launch.assert_not_called()


def test_brave_returns_urls_only_and_keeps_key_out_of_errors(settings):
    settings = settings.model_copy(update={"brave_api_key": SecretStr("test-private-key")})
    queries = []

    def handler(request):
        queries.append(request.url.params["q"])
        assert request.headers["X-Subscription-Token"] == "test-private-key"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {"url": "https://a.com/award", "description": "a snippet is not evidence"},
                        {"url": "file:///private"},
                    ]
                }
            },
        )

    search = BraveSearchProvider(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda delay: None,
    )
    assert search.search('"2026/123456" yüklenici') == ["https://a.com/award"]
    assert queries == ['"2026/123456" yüklenici']
    assert "test-private-key" not in repr(settings)
    search.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401)))
    with pytest.raises(CollectionError) as failure:
        search.search("test")
    assert "test-private-key" not in str(failure.value)
