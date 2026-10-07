"""vcrpy wiring shared by the tests and `run_once --replay`.

Cassettes live in `tests/cassettes/<source>.yaml`. Every secret configured in `Settings` is
scrubbed from request URIs, headers, bodies and response bodies before a cassette is written, and
the same filter is applied to live requests before matching, so replay works without keys.

Record (hits live APIs, uses real keys): `VCR_RECORD=once uv run pytest tests/test_ingest_x.py`.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import vcr
from vcr.request import Request

from brokeberg.config import get_settings
from brokeberg.ingest import http

CASSETTES = Path(__file__).resolve().parents[2] / "tests" / "cassettes"
REDACTED = "REDACTED"
# Cassettes were recorded with this `since`; replay must use it too (it is in the request URLs).
REPLAY_SINCE = datetime(2026, 9, 30, tzinfo=UTC)
SECRET_FIELDS = (
    "congress_api_key",
    "fred_api_key",
    "bls_api_key",
    "data_gov_api_key",
    "census_api_key",
    "x_bearer_token",
    "anthropic_api_key",
)


def secrets() -> list[str]:
    s = get_settings()
    values = [getattr(s, f) for f in SECRET_FIELDS]
    return [v for v in values if v and len(v) >= 8]


def _scrub(text: str) -> str:
    for secret in secrets():
        text = text.replace(secret, REDACTED)
    return text


def _scrub_bytes(body: Any) -> Any:
    if isinstance(body, bytes):
        return _scrub(body.decode("utf-8", errors="surrogateescape")).encode(
            "utf-8", errors="surrogateescape"
        )
    if isinstance(body, str):
        return _scrub(body)
    return body


def _before_request(request: Request) -> Request:
    request.uri = _scrub(request.uri)
    request.body = _scrub_bytes(request.body)
    return request


def _before_response(response: dict[str, Any]) -> dict[str, Any]:
    body = response.get("body", {})
    if "string" in body:
        body["string"] = _scrub_bytes(body["string"])
    return response


def recorder() -> vcr.VCR:
    return vcr.VCR(
        cassette_library_dir=str(CASSETTES),
        record_mode=os.environ.get("VCR_RECORD", "none"),
        match_on=["method", "scheme", "host", "path", "query"],
        filter_query_parameters=[("api_key", REDACTED), ("registrationkey", REDACTED)],
        filter_headers=[("authorization", REDACTED), ("x-api-key", REDACTED)],
        before_record_request=_before_request,
        before_record_response=_before_response,
        decode_compressed_response=True,
    )


def recording() -> bool:
    return os.environ.get("VCR_RECORD", "none") != "none"


@contextmanager
def cassette(source: str) -> Iterator[Any]:
    """`with cassette("fred"): ...`. Rate limiting is switched off while replaying."""
    limiter = http.LIMITER
    saved = (limiter.min_interval, limiter.per_host)
    if not recording():
        limiter.min_interval, limiter.per_host = 0.0, {}
    try:
        with recorder().use_cassette(f"{source}.yaml") as cass:
            yield cass
    finally:
        limiter.min_interval, limiter.per_host = saved
