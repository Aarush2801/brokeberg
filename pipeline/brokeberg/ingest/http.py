"""Shared HTTP plumbing: client factory, retries with backoff, per-domain rate limit, robots.txt.

Every connector goes through `request()`, so retries and politeness are uniform. robots.txt is
fetched with the same client (not urllib), which keeps it inside recorded cassettes in tests.
"""

import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

USER_AGENT = "brokeberg/0.1 (political-economic research; +https://github.com/Aarush2801/brokeberg)"
DEFAULT_MIN_INTERVAL = 0.5  # seconds between requests to the same host
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def make_client(**kwargs: Any) -> httpx.Client:
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    return httpx.Client(timeout=30.0, follow_redirects=True, headers=headers, **kwargs)


class RateLimiter:
    """Minimum interval between calls per host. `clock`/`sleep` are injectable for tests."""

    def __init__(
        self,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        per_host: dict[str, float] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self.per_host = per_host or {}
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    def wait(self, url: str) -> None:
        host = urlsplit(url).netloc
        interval = self.per_host.get(host, self.min_interval)
        last = self._last.get(host)
        if last is not None:
            remaining = interval - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last[host] = self._clock()


LIMITER = RateLimiter()


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRY_STATUSES
    return isinstance(exc, httpx.TransportError)


@retry(
    retry=retry_if_exception(_retryable),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)
def request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    limiter: RateLimiter = LIMITER,
    **kwargs: Any,
) -> httpx.Response:
    limiter.wait(url)
    response = client.request(method, url, **kwargs)
    response.raise_for_status()
    return response


def get(client: httpx.Client, url: str, **kwargs: Any) -> httpx.Response:
    return request(client, "GET", url, **kwargs)


_ROBOTS: dict[str, RobotFileParser] = {}
DISALLOW_ALL = ["User-agent: *", "Disallow: /"]


def robots_ok(client: httpx.Client, url: str, user_agent: str = USER_AGENT) -> bool:
    """True if robots.txt allows fetching `url`. Cached per host for the process lifetime.

    Same semantics as the stdlib: a missing robots.txt allows everything; 401/403 disallows.
    """
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    parser = _ROBOTS.get(origin)
    if parser is None:
        parser = RobotFileParser(f"{origin}/robots.txt")
        try:
            resp = client.get(f"{origin}/robots.txt")
        except httpx.HTTPError as exc:
            log.warning("robots.txt fetch failed for %s (%s); treating as disallowed", origin, exc)
            parser.parse(DISALLOW_ALL)
        else:
            if resp.status_code in (401, 403):
                parser.parse(DISALLOW_ALL)
            elif resp.status_code >= 400:
                parser.parse([])
            else:
                parser.parse(resp.text.splitlines())
        _ROBOTS[origin] = parser
    return parser.can_fetch(user_agent, url)


def clear_robots_cache() -> None:
    _ROBOTS.clear()
