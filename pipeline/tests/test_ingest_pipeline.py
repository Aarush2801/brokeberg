from collections.abc import Iterable
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from brokeberg.db.models import RawItem
from brokeberg.ingest import http
from brokeberg.ingest.base import RawRecord
from brokeberg.ingest.pipeline import content_hash, write_raw
from brokeberg.ingest.replay import CASSETTES, secrets
from brokeberg.taxonomy import SourceType


class FakeConnector:
    source = "fake"
    source_type = SourceType.GOVERNMENT_PRIMARY

    def __init__(self, records: list[RawRecord]) -> None:
        self.records = records

    def fetch(self, session: Session, since: datetime) -> Iterable[RawRecord]:
        return self.records


def _rec(n: int) -> RawRecord:
    return RawRecord(
        url=f"https://example.gov/item/{n}",
        text=f"item {n}",
        event_time=datetime(2026, 10, 1, tzinfo=UTC),
        raw_payload={"n": n, "nested": {"b": 2, "a": 1}},
        entity_ids=["bioguide:O000174"],
        unresolved=["Somebody Unknown"],
    )


# --- pure ------------------------------------------------------------------------------------


def test_content_hash_is_stable_and_key_order_independent() -> None:
    a = content_hash("s", "u", {"x": 1, "y": {"b": 2, "a": 1}})
    b = content_hash("s", "u", {"y": {"a": 1, "b": 2}, "x": 1})
    assert a == b and len(a) == 64
    assert content_hash("s", "u", {"x": 2}) != a
    assert content_hash("other", "u", {"x": 1, "y": {"b": 2, "a": 1}}) != a


def test_rate_limiter_spaces_calls_per_host() -> None:
    now = [100.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    limiter = http.RateLimiter(min_interval=1.0, clock=lambda: now[0], sleep=sleep)
    limiter.wait("https://a.gov/1")
    limiter.wait("https://b.gov/1")  # different host: no wait
    now[0] += 0.25
    limiter.wait("https://a.gov/2")
    assert slept == [pytest.approx(0.75)]


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_robots_ok_parses_and_caches() -> None:
    calls: list[str] = []

    def handle(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")

    http.clear_robots_cache()
    client = _client(httpx.MockTransport(handle))
    assert http.robots_ok(client, "https://site.test/public/page")
    assert not http.robots_ok(client, "https://site.test/private/page")
    assert calls == ["https://site.test/robots.txt"]


@pytest.mark.parametrize(("status", "allowed"), [(404, True), (403, False)])
def test_robots_ok_status_semantics(status: int, allowed: bool) -> None:
    http.clear_robots_cache()
    client = _client(httpx.MockTransport(lambda req: httpx.Response(status)))
    assert http.robots_ok(client, "https://site.test/x") is allowed


def test_request_retries_on_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http.request.retry, "sleep", lambda s: None)  # type: ignore[attr-defined]
    responses = iter([httpx.Response(503), httpx.Response(200, text="ok")])
    client = _client(httpx.MockTransport(lambda req: next(responses)))
    limiter = http.RateLimiter(min_interval=0)
    assert http.get(client, "https://x.test/", limiter=limiter).text == "ok"


def test_cassettes_contain_no_secrets() -> None:
    values = secrets()
    for path in CASSETTES.glob("*.yaml"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for secret in values:
            assert secret not in text, f"secret leaked into {path.name}"


# --- db ---------------------------------------------------------------------------------------


def test_write_raw_dedups_same_item(db_session: Session) -> None:
    conn = FakeConnector([_rec(1), _rec(2), _rec(1)])
    first = write_raw(db_session, conn, conn.fetch(db_session, datetime.now(UTC)))
    assert (first.fetched, first.inserted, first.skipped) == (3, 2, 1)

    again = write_raw(db_session, conn, conn.fetch(db_session, datetime.now(UTC)))
    assert (again.inserted, again.skipped) == (0, 3)

    rows = db_session.scalars(select(RawItem).where(RawItem.source == "fake")).all()
    assert len(rows) == 2
    payload = rows[0].payload_jsonb
    assert payload["_resolved"] == ["bioguide:O000174"]
    assert payload["_unresolved"] == ["Somebody Unknown"]
    assert db_session.scalar(select(func.count()).select_from(RawItem)) >= 2
