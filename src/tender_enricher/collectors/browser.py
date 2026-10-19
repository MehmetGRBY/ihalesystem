"""Opt-in renderer, preserving access checks and a small request budget."""

from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Route, sync_playwright

from tender_enricher.collectors.web import Document, WebClient, check_challenge
from tender_enricher.errors import CollectionError


class BrowserClient:
    def __init__(self, web: WebClient) -> None:
        self.web = web

    def begin_tender(self) -> None:
        self.web.begin_tender()

    def close(self) -> None:
        self.web.close()

    def fetch(self, url: str) -> Document:
        # HTTP preflight stops at protected access before any browser is launched.
        initial = self.web.fetch(url)
        errors: list[CollectionError] = []
        requests = 0

        def guard(route: Route) -> None:
            nonlocal requests
            request = route.request
            if (
                request.method != "GET"
                or request.resource_type not in {"document", "script", "xhr", "fetch"}
                or urlsplit(request.url).netloc != urlsplit(initial.final_url).netloc
            ):
                route.abort()
                return
            requests += 1
            if requests > 15:
                errors.append(
                    CollectionError("browser_budget_exceeded", "Browser request budget reached.")
                )
                route.abort()
                return
            try:
                self.web.ensure_allowed(request.url)
                self.web.wait_for_host(request.url)
                route.continue_()
            except CollectionError as error:
                errors.append(error)
                route.abort()

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    context = browser.new_context(
                        user_agent=self.web.settings.user_agent,
                        service_workers="block",
                        accept_downloads=False,
                    )
                    context.route("**/*", guard)
                    context.route_web_socket("**/*", lambda websocket: websocket.close())
                    page = context.new_page()
                    response = page.goto(
                        initial.final_url,
                        wait_until="networkidle",
                        timeout=self.web.settings.request_timeout_seconds * 1000,
                    )
                    if errors:
                        raise errors[0]
                    if response is None or response.status != 200:
                        raise CollectionError(
                            "browser_http_error", "Browser source did not return HTTP 200."
                        )
                    body = page.content()
                    if len(body.encode()) > self.web.settings.max_response_bytes:
                        raise CollectionError(
                            "response_too_large", "Rendered source exceeds size limit."
                        )
                    check_challenge(body)
                    return Document(url, page.url, body)
                finally:
                    browser.close()
        except PlaywrightError as error:
            if errors:
                raise errors[0] from error
            raise CollectionError(
                "browser_failed", "Browser rendering failed; check Chromium installation."
            ) from error
