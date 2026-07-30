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
                    f"Request limit reached ({self.maximum}). "
                    "Increase --max-requests explicitly."
                )
            self._used += 1
            return self._used

    @property
    def used(self) -> int:
        with self._lock:
            return self._used


class GlobalRateLimiter:
    """Thread-safe global spacing between request starts."""

    def __init__(self, delay_seconds: float) -> None:
        if delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")
        self.delay_seconds = delay_seconds
        self._next_allowed = 0.0
        self._lock = threading.Lock()
        self.total_wait_seconds = 0.0

    def wait(self) -> float:
        if self.delay_seconds == 0:
            return 0.0
        started = time.monotonic()
        with self._lock:
            now = time.monotonic()
            sleep_for = max(0.0, self._next_allowed - now)
            if sleep_for:
                time.sleep(sleep_for)
                now = time.monotonic()
            self._next_allowed = now + self.delay_seconds
        waited = time.monotonic() - started
        self.total_wait_seconds += waited
        return waited


class AdaptiveConcurrencyLimiter:
    """Bounded additive-increase/multiplicative-decrease HTTP limiter."""

    def __init__(self, minimum: int, maximum: int, *, enabled: bool = True) -> None:
        if minimum < 1 or maximum < minimum:
            raise ValueError("invalid adaptive concurrency limits")
        self.minimum = minimum
        self.maximum = maximum
        self.enabled = enabled
        # Start at the explicitly configured ceiling for immediate throughput.
        # AIMD backs off only on transport failures or HTTP 429.
        self._limit = maximum
        self._active = 0
        self._successes = 0
        self._condition = threading.Condition()

    def acquire(self) -> float:
        started = time.monotonic()
        with self._condition:
            while self._active >= self._limit:
                self._condition.wait(timeout=0.1)
            self._active += 1
        return time.monotonic() - started

    def release(
        self,
        *,
        status_code: int | None,
        transport_failed: bool | None = None,
        failed: bool | None = None,
        elapsed: float | None = None,
    ) -> None:
        # ``failed`` and ``elapsed`` preserve the v0.6.x internal call shape.
        del elapsed
        transport_error = bool(
            transport_failed if transport_failed is not None else failed
        )
        with self._condition:
            self._active = max(0, self._active - 1)
            if not self.enabled:
                self._condition.notify_all()
                return

            # A 5xx response may be the expected FALSE side of a boolean oracle.
            # Only transport failures and explicit throttling are congestion signals.
            throttled = status_code == 429
            if transport_error or throttled:
                self._limit = max(self.minimum, self._limit // 2)
                self._successes = 0
            else:
                self._successes += 1
                threshold = max(8, self._limit * 3)
                if self._successes >= threshold and self._limit < self.maximum:
                    self._limit += 1
                    self._successes = 0
            self._condition.notify_all()

    @property
    def limit(self) -> int:
        with self._condition:
            return self._limit


@dataclass(slots=True)
class HttpMetrics:
    network_seconds: float = 0.0
    rate_limit_wait_seconds: float = 0.0
    concurrency_wait_seconds: float = 0.0
    retries: int = 0
    errors: int = 0
    responses: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(
        self,
        *,
        network: float = 0.0,
        rate_wait: float = 0.0,
        concurrency_wait: float = 0.0,
        retry: bool = False,
        error: bool = False,
        response: bool = False,
    ) -> None:
        with self._lock:
            self.network_seconds += network
            self.rate_limit_wait_seconds += rate_wait
            self.concurrency_wait_seconds += concurrency_wait
            self.retries += int(retry)
            self.errors += int(error)
            self.responses += int(response)

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            return {
                "network_seconds": round(self.network_seconds, 6),
                "rate_limit_wait_seconds": round(
                    self.rate_limit_wait_seconds,
                    6,
                ),
                "concurrency_wait_seconds": round(
                    self.concurrency_wait_seconds,
                    6,
                ),
                "retries": self.retries,
                "errors": self.errors,
                "responses": self.responses,
            }


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
    adaptive_concurrency: bool = True
    min_concurrency: int = 1
    max_concurrency: int = 4

    def __post_init__(self) -> None:
        if self.timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if self.retries < 0 or self.retries > 5:
            raise ValueError("retries must be between 0 and 5")
        if not self.parameter and not self.url_template:
            raise ValueError("parameter is required when url_template is not used")
        if self.min_concurrency < 1 or self.max_concurrency < self.min_concurrency:
            raise ValueError("invalid concurrency range")


class HttpClient:
    """Thread-safe HTTP client using one requests.Session per worker thread."""

    def __init__(self, config: HttpConfig) -> None:
        self.config = config
        self.budget = RequestBudget(config.max_requests)
        self.rate_limiter = GlobalRateLimiter(config.delay)
        self.concurrency = AdaptiveConcurrencyLimiter(
            config.min_concurrency,
            config.max_concurrency,
            enabled=config.adaptive_concurrency,
        )
        self.metrics = HttpMetrics()
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
        return urlunsplit(
            (split.scheme, split.netloc, split.path, query, split.fragment)
        )

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
            self.config.url,
            self.config.parameter,
            payload,
        )

    def get(self, payload: str) -> Response:
        url = self.build_url(payload)
        last_error: RequestException | None = None
        for attempt in range(self.config.retries + 1):
            self.budget.consume()
            rate_wait = self.rate_limiter.wait()
            concurrency_wait = self.concurrency.acquire()
            started = time.monotonic()
            try:
                response = self._session().get(
                    url,
                    timeout=self.config.timeout,
                    verify=self.config.verify_tls,
                    allow_redirects=False,
                )
            except RequestException as exc:
                elapsed = time.monotonic() - started
                self.concurrency.release(
                    status_code=None,
                    transport_failed=True,
                )
                self.metrics.add(
                    network=elapsed,
                    rate_wait=rate_wait,
                    concurrency_wait=concurrency_wait,
                    error=True,
                    retry=attempt < self.config.retries,
                )
                last_error = exc
                if attempt >= self.config.retries:
                    break
                continue

            elapsed = time.monotonic() - started
            self.concurrency.release(
                status_code=response.status_code,
                transport_failed=False,
            )
            self.metrics.add(
                network=elapsed,
                rate_wait=rate_wait,
                concurrency_wait=concurrency_wait,
                response=True,
            )
            return response
        raise HttpRequestError(f"HTTP request failed: {last_error}") from last_error

    @property
    def requests_used(self) -> int:
        return self.budget.used

    def performance_snapshot(self) -> dict[str, float | int]:
        return {
            **self.metrics.snapshot(),
            "adaptive_limit": self.concurrency.limit,
        }
