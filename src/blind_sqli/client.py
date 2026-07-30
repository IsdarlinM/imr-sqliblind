from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import cast
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import requests
from requests import Response, Session
from requests.exceptions import RequestException


class RequestLimitExceeded(RuntimeError):
    pass


class HttpRequestError(RuntimeError):
    pass


class RequestBudget:
    def __init__(self, maximum: int) -> None:
        if maximum < 1:
            raise ValueError("maximum must be at least 1")
        self.maximum = maximum
        self._used = 0
        self._lock = threading.Lock()

    def consume(self) -> int:
        with self._lock:
            if self._used >= self.maximum:
                raise RequestLimitExceeded(
                    f"Request limit reached ({self.maximum}). Increase --max-requests explicitly."
                )
            self._used += 1
            return self._used

    @property
    def used(self) -> int:
        with self._lock:
            return self._used


class GlobalRateLimiter:
    """Thread-safe global spacing between requests."""

    def __init__(self, delay_seconds: float) -> None:
        if delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")
        self.delay_seconds = delay_seconds
        self._next_allowed = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        if self.delay_seconds == 0:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = max(0.0, self._next_allowed - now)
            if sleep_for:
                time.sleep(sleep_for)
                now = time.monotonic()
            self._next_allowed = now + self.delay_seconds


@dataclass(slots=True)
class HttpConfig:
    url: str
    parameter: str = "id"
    url_template: str | None = None
    timeout: float = 10.0
    verify_tls: bool = True
    retries: int = 1
    delay: float = 0.1
    max_requests: int = 5000
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    proxy: str | None = None

    def __post_init__(self) -> None:
        if self.timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if self.retries < 0 or self.retries > 5:
            raise ValueError("retries must be between 0 and 5")
        if not self.parameter and not self.url_template:
            raise ValueError("parameter is required when url_template is not used")


class HttpClient:
    """Thread-safe HTTP client using one requests.Session per worker thread."""

    def __init__(self, config: HttpConfig) -> None:
        self.config = config
        self.budget = RequestBudget(config.max_requests)
        self.rate_limiter = GlobalRateLimiter(config.delay)
        self._local = threading.local()

    def _session(self) -> Session:
        session = cast(Session | None, getattr(self._local, "session", None))
        if session is None:
            session = requests.Session()
            session.headers.update(self.config.headers)
            session.cookies.update(self.config.cookies)
            if self.config.proxy:
                session.proxies.update(
                    {"http": self.config.proxy, "https": self.config.proxy}
                )
            self._local.session = session
        return session

    @staticmethod
    def _replace_query_parameter(url: str, parameter: str, payload: str) -> str:
        split = urlsplit(url)
        pairs = parse_qsl(split.query, keep_blank_values=True)
        replaced = False
        updated: list[tuple[str, str]] = []
        for key, value in pairs:
            if key == parameter and not replaced:
                updated.append((key, payload))
                replaced = True
            else:
                updated.append((key, value))
        if not replaced:
            updated.append((parameter, payload))
        query = urlencode(updated, doseq=True)
        return urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment))

    def build_url(self, payload: str) -> str:
        if self.config.url_template:
            template = self.config.url_template
            marker = "{{PAYLOAD}}" if "{{PAYLOAD}}" in template else "[TO_REPLACE]"
            if marker not in template:
                raise ValueError(
                    "URL template must contain {{PAYLOAD}} or [TO_REPLACE]."
                )
            return template.replace(marker, quote(payload, safe=""))
        return self._replace_query_parameter(
            self.config.url, self.config.parameter, payload
        )

    def get(self, payload: str) -> Response:
        url = self.build_url(payload)
        last_error: RequestException | None = None
        for attempt in range(self.config.retries + 1):
            self.budget.consume()
            self.rate_limiter.wait()
            try:
                return self._session().get(
                    url,
                    timeout=self.config.timeout,
                    verify=self.config.verify_tls,
                    allow_redirects=False,
                )
            except RequestException as exc:
                last_error = exc
                if attempt >= self.config.retries:
                    break
        raise HttpRequestError(f"HTTP request failed: {last_error}") from last_error

    @property
    def requests_used(self) -> int:
        return self.budget.used
