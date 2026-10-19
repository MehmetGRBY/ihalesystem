"""Shared access policy; collectors never bypass it."""

import ipaddress
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from tender_enricher.config import Settings
from tender_enricher.errors import CollectionError


@dataclass(frozen=True)
class Document:
    url: str
    final_url: str
    body: str
    is_demo: bool = False


def public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise CollectionError("unsafe_url", "Only public HTTP(S) sources are supported.")
    if parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
        raise CollectionError("unsafe_url", "Credentials and nonstandard ports are forbidden.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError as error:
        raise CollectionError("dns_failed", "Source hostname could not be resolved.") from error
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise CollectionError(
            "unsafe_url", "Private, local and reserved destinations are forbidden."
        )


def check_challenge(body: str) -> None:
    lowered = body.lower()
    prompts = (
        "verify you are human",
        "insan olduğunuzu doğrulayın",
        "access denied",
        "just a moment...",
    )
    widget = "g-recaptcha" in lowered or "hcaptcha" in lowered
    if "cf-chl-" not in lowered and not widget and not any(p in lowered for p in prompts):
        return
    soup = BeautifulSoup(body, "lxml")
    for node in soup.select("script, style, noscript, [hidden]"):
        node.decompose()
    visible = soup.get_text(" ", strip=True).lower()
    protected = "cf-chl-" in lowered or any(prompt in visible for prompt in prompts)
    if widget and not protected:
        # A CAPTCHA on a contact/newsletter form does not gate the surrounding
        # public page. Never submit or render the form to obtain its contents.
        for node in soup.select("form, iframe"):
            node.decompose()
        public_text = soup.get_text(" ", strip=True)
        public_contacts = soup.select('a[href^="mailto:"], a[href^="tel:"], address')
        readable = (bool(public_contacts) and len(public_text) >= 50) or (
            len(public_text) >= 300 and soup.find(["h1", "h2", "article"]) is not None
        )
        protected = not readable
    if protected:
        raise CollectionError("access_protected", "Access protection detected; collection stopped.")


class WebClient:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        validate_url: Callable[[str], None] = public_url,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.client = client or httpx.Client(
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": settings.user_agent},
        )
        self.validate_url = validate_url
        self.sleep = sleep
        self.clock = clock
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser] = {}
        self._documents: dict[str, Document] = {}
        self._page_count = 0

    def close(self) -> None:
        self.client.close()

    def begin_tender(self) -> None:
        self._documents.clear()
        self._page_count = 0

    def wait_for_host(self, url: str, interval: float | None = None) -> None:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        origin = f"{parsed.scheme}://{parsed.netloc}"
        robots = self._robots.get(origin)
        if robots:
            crawl_delay = robots.crawl_delay(self.settings.user_agent)
            interval = max(interval or 0, float(crawl_delay) if crawl_delay is not None else 0)
            request_rate = robots.request_rate(self.settings.user_agent)
            if request_rate and request_rate.requests > 0:
                interval = max(interval or 0, request_rate.seconds / request_rate.requests)
        delay = max(self.settings.request_interval_seconds, interval or 0)
        if delay > 60:
            raise CollectionError(
                "crawl_deferred", "Source requires a longer crawl interval; skipped."
            )
        previous = self._last_request.get(host)
        if previous is not None:
            self.sleep(max(0, previous + delay - self.clock()))
        self._last_request[host] = self.clock()

    def ensure_allowed(self, url: str) -> None:
        self.validate_url(url)
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            robots_url = origin + "/robots.txt"
            response, _ = self._get(robots_url, enforce_robots=False)
            parser = RobotFileParser(robots_url)
            if response.status_code == 404:
                parser.parse([])
            elif response.status_code == 200:
                check_challenge(response.text)
                parser.parse(response.text.splitlines())
            else:
                raise CollectionError(
                    "robots_unavailable", "Robots policy could not be established."
                )
            self._robots[origin] = parser
        parser = self._robots[origin]
        if not parser.can_fetch(self.settings.user_agent, url):
            raise CollectionError("robots_denied", "Robots policy disallows this source.")

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        value = response.headers.get("Retry-After")
        delay = float(2**attempt)
        if value:
            try:
                delay = max(delay, float(value))
            except ValueError:
                try:
                    delay = max(
                        delay, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
                    )
                except (ValueError, TypeError):
                    pass
        if delay > self.settings.max_retry_delay_seconds:
            raise CollectionError(
                "retry_deferred", "Source requested a later retry; collection stopped."
            )
        return delay

    def _request(self, url: str) -> httpx.Response:
        for attempt in range(self.settings.max_attempts):
            self.validate_url(url)
            self.wait_for_host(url)
            try:
                with self.client.stream("GET", url) as streamed:
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in streamed.iter_bytes():
                        size += len(chunk)
                        if size > self.settings.max_response_bytes:
                            raise CollectionError(
                                "response_too_large", "Source exceeds the page-size limit."
                            )
                        chunks.append(chunk)
                    response = httpx.Response(
                        streamed.status_code,
                        # iter_bytes() already decoded compression. Preserve semantic
                        # headers, but do not decode this buffered body a second time.
                        headers={
                            key: value
                            for key, value in streamed.headers.items()
                            if key.lower()
                            not in {"content-encoding", "content-length", "transfer-encoding"}
                        },
                        content=b"".join(chunks),
                        request=streamed.request,
                    )
            except httpx.TransportError as error:
                if attempt + 1 == self.settings.max_attempts:
                    raise CollectionError(
                        "network_failed", "Source request failed after bounded retries."
                    ) from error
                self.sleep(min(float(2**attempt), self.settings.max_retry_delay_seconds))
                continue
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt + 1 == self.settings.max_attempts:
                    raise CollectionError(
                        "retry_exhausted", "Source remained unavailable after bounded retries."
                    )
                self.sleep(self._retry_delay(response, attempt))
                continue
            if response.status_code in {401, 403}:
                raise CollectionError(
                    "access_denied", "Source requires protected access; collection stopped."
                )
            return response
        raise CollectionError("network_failed", "Source request did not complete.")

    def _get(self, url: str, *, enforce_robots: bool) -> tuple[httpx.Response, str]:
        current = url
        for _ in range(5):
            if enforce_robots:
                self.ensure_allowed(current)
            response = self._request(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                if not location:
                    raise CollectionError(
                        "invalid_redirect", "Source returned an invalid redirect."
                    )
                current = urljoin(current, location)
                continue
            return response, current
        raise CollectionError("too_many_redirects", "Source exceeded the redirect limit.")

    def fetch(self, url: str) -> Document:
        if url in self._documents:
            return self._documents[url]
        if self._page_count >= self.settings.max_pages_per_tender:
            raise CollectionError("page_budget_exceeded", "Per-tender source-page limit reached.")
        self._page_count += 1
        response, final_url = self._get(url, enforce_robots=True)
        if response.status_code != 200:
            raise CollectionError("http_error", f"Source returned HTTP {response.status_code}.")
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            raise CollectionError(
                "unsupported_content", "Only public HTML pages are supported in MVP."
            )
        check_challenge(response.text)
        document = Document(url, final_url, response.text)
        self._documents[url] = document
        return document
