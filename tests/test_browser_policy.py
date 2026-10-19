from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tender_enricher.collectors.browser import BrowserClient
from tender_enricher.collectors.web import Document
from tender_enricher.errors import CollectionError


def renderer(monkeypatch, settings, requests, body="<p>Rendered public page</p>"):
    web = Mock()
    web.settings = settings
    web.fetch.return_value = Document("https://a.com/page", "https://a.com/page", "<p>Initial</p>")
    context, page, browser = Mock(), Mock(), Mock()
    page.url = "https://a.com/page"
    page.content.return_value = body
    context.new_page.return_value = page
    browser.new_context.return_value = context
    playwright = Mock()
    playwright.chromium.launch.return_value = browser
    manager = Mock()
    manager.__enter__ = Mock(return_value=playwright)
    manager.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("tender_enricher.collectors.browser.sync_playwright", lambda: manager)
    routes = []

    def navigate(*args, **kwargs):
        guard = context.route.call_args.args[1]
        for method, kind, url in requests:
            route = Mock()
            route.request = SimpleNamespace(method=method, resource_type=kind, url=url)
            routes.append(route)
            guard(route)
        return SimpleNamespace(status=200)

    page.goto.side_effect = navigate
    return BrowserClient(web), web, routes, browser, context


def test_renderer_only_allows_same_origin_get_resources(monkeypatch, settings):
    client, web, routes, browser, context = renderer(
        monkeypatch,
        settings,
        [
            ("GET", "document", "https://a.com/page"),
            ("GET", "script", "https://a.com/script.js"),
            ("POST", "xhr", "https://a.com/login"),
            ("GET", "script", "https://external.com/tracker.js"),
            ("GET", "image", "https://a.com/photo.png"),
        ],
    )
    assert "Rendered" in client.fetch("https://a.com/page").body
    assert web.ensure_allowed.call_count == 2
    assert all(route.continue_.called for route in routes[:2])
    assert all(route.abort.called for route in routes[2:])
    assert context.route_web_socket.called
    assert context.new_page.called
    assert browser.close.called


def test_renderer_budget_stops_instead_of_aggressive_loading(monkeypatch, settings):
    client, _, routes, browser, _ = renderer(
        monkeypatch,
        settings,
        [("GET", "fetch", f"https://a.com/resource/{index}") for index in range(16)],
    )
    with pytest.raises(CollectionError) as failure:
        client.fetch("https://a.com/page")
    assert failure.value.code == "browser_budget_exceeded"
    assert routes[-1].abort.called
    assert browser.close.called


def test_renderer_rechecks_robots_and_detects_rendered_protection(monkeypatch, settings):
    client, web, routes, browser, _ = renderer(
        monkeypatch, settings, [("GET", "xhr", "https://a.com/private")]
    )
    web.ensure_allowed.side_effect = CollectionError("robots_denied", "Blocked by robots")
    with pytest.raises(CollectionError) as failure:
        client.fetch("https://a.com/page")
    assert failure.value.code == "robots_denied"
    assert routes[0].abort.called and browser.close.called

    client, _, _, browser, _ = renderer(monkeypatch, settings, [], body="verify you are human")
    with pytest.raises(CollectionError) as failure:
        client.fetch("https://a.com/page")
    assert failure.value.code == "access_protected"
    assert browser.close.called
