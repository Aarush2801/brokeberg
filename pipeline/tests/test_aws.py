import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import Session

from brokeberg.aws import handlers, secrets
from brokeberg.cluster import run as cluster_run
from brokeberg.db import session as db_session
from brokeberg.extract import run as extract_run
from brokeberg.graph import run as graph_run
from brokeberg.ingest import run_once
from brokeberg.ingest.base import Stats


class FakeSecrets:
    def __init__(self, app: dict[str, Any]) -> None:
        self.values = {secrets.APP_SECRET_ID: app}

    def get_secret_value(self, SecretId: str) -> dict[str, str]:  # noqa: N803 - boto3 casing
        return {"SecretString": json.dumps(self.values[SecretId])}


class FakeSqs:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_message(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)


# --- secrets ----------------------------------------------------------------------------------


def test_resolve_uppercases_keys_and_stringifies_values() -> None:
    env = secrets.resolve(FakeSecrets({"llm_provider": "bedrock", "X_MAX_RESULTS": 5}))
    assert env == {"LLM_PROVIDER": "bedrock", "X_MAX_RESULTS": "5"}


def test_database_url_is_tls_with_no_password() -> None:
    url = make_url(
        secrets.database_url("db.cluster-x.us-east-2.rds.amazonaws.com", "postgres", "brokeberg")
    )
    assert url.drivername == "postgresql+psycopg"
    assert url.password is None  # IAM token supplied per connection
    assert url.host.endswith("us-east-2.rds.amazonaws.com") and url.port == 5432
    assert url.username == "postgres" and url.database == "brokeberg"
    assert url.query["sslmode"] == "require"


def test_iam_auth_signs_each_connection_with_a_fresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int, str]] = []

    def fake_token(host: str, port: int, user: str) -> str:
        calls.append((host, port, user))
        return f"token-{len(calls)}"

    monkeypatch.setattr(db_session, "iam_token", fake_token)
    engine = create_engine("postgresql+psycopg://postgres@db.example:5432/brokeberg")
    db_session.use_iam_auth(engine)
    for expected in ("token-1", "token-2"):
        cparams: dict[str, Any] = {}
        engine.dialect.dispatch.do_connect(engine.dialect, None, [], cparams)
        assert cparams["password"] == expected
    assert calls == [("db.example", 5432, "postgres")] * 2


def test_load_never_overrides_process_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_MAX_RESULTS", "12")
    monkeypatch.delenv("LLM_MODEL_CHEAP", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    secrets.load(FakeSecrets({"X_MAX_RESULTS": "5", "LLM_MODEL_CHEAP": "haiku"}))
    try:
        assert os.environ["X_MAX_RESULTS"] == "12"
        assert os.environ["LLM_MODEL_CHEAP"] == "haiku"
    finally:
        os.environ.pop("LLM_MODEL_CHEAP", None)
        os.environ.pop("DATABASE_URL", None)


# --- handlers ---------------------------------------------------------------------------------


@pytest.fixture
def warm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the Secrets Manager cold start."""
    monkeypatch.setattr(handlers, "_loaded", True)


def test_cold_start_keeps_api_keys_out_of_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    # httpx logs request URLs (with ?api_key=...) at INFO; the root logger goes to INFO.
    monkeypatch.setattr(handlers, "_loaded", False)
    monkeypatch.setattr(secrets, "load", lambda: None)
    root, httpx_log = logging.getLogger(), logging.getLogger("httpx")
    saved = root.level, httpx_log.level
    httpx_log.setLevel(logging.NOTSET)
    try:
        handlers._cold_start()
        assert root.isEnabledFor(logging.INFO)
        assert not httpx_log.isEnabledFor(logging.INFO)
    finally:
        root.setLevel(saved[0])
        httpx_log.setLevel(saved[1])


def _ingest_stats(monkeypatch: pytest.MonkeyPatch, stats: Stats) -> list[Any]:
    calls: list[Any] = []

    def fake_run(since: datetime, replay: bool = False, only: Any = None) -> list[Stats]:
        calls.append(only)
        return [stats]

    monkeypatch.setattr(run_once, "run", fake_run)
    monkeypatch.setenv("SOURCE", "x")
    monkeypatch.setenv("PROCESS_QUEUE_URL", "https://sqs/q")
    return calls


@pytest.mark.usefixtures("warm")
def test_ingest_runs_its_source_and_enqueues_new_items(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _ingest_stats(monkeypatch, Stats(source="x", fetched=3, inserted=2, skipped=1))
    sqs = FakeSqs()
    assert handlers.ingest({}, sqs=sqs)["inserted"] == 2
    assert calls == [["x"]]
    assert [json.loads(m["MessageBody"]) for m in sqs.sent] == [{"source": "x", "inserted": 2}]
    assert sqs.sent[0]["MessageGroupId"] == handlers.PROCESS_GROUP


@pytest.mark.usefixtures("warm")
def test_ingest_with_nothing_new_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _ingest_stats(monkeypatch, Stats(source="x", fetched=3, skipped=3))
    sqs = FakeSqs()
    handlers.ingest({}, sqs=sqs)
    assert sqs.sent == []


@pytest.mark.usefixtures("warm")
def test_ingest_failure_raises_so_lambda_reports_it(monkeypatch: pytest.MonkeyPatch) -> None:
    _ingest_stats(monkeypatch, Stats(source="x", note="FAILED: HTTPError: 503"))
    with pytest.raises(RuntimeError, match="FAILED"):
        handlers.ingest({}, sqs=FakeSqs())


def _process(monkeypatch: pytest.MonkeyPatch, used: int, cap: int) -> list[int | None]:
    limits: list[int | None] = []
    monkeypatch.setenv("EXTRACT_DAILY_CAP", str(cap))
    monkeypatch.setattr(handlers, "extracted_today", lambda session, now: used)
    monkeypatch.setattr(
        extract_run, "run", lambda limit=None, **_: limits.append(limit) or {"extracted": 1}
    )
    monkeypatch.setattr(cluster_run, "run", lambda **_: {"new": 1})
    monkeypatch.setattr(graph_run, "run", lambda: {"heads": 1})
    return limits


@pytest.mark.usefixtures("warm", "db_engine")
def test_process_extracts_only_what_is_left_of_the_daily_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits = _process(monkeypatch, used=25, cap=30)
    out = handlers.process({"Records": []})
    assert limits == [5]
    assert out["cluster"] == {"new": 1} and out["graph"] == {"heads": 1}


@pytest.mark.usefixtures("warm", "db_engine")
def test_process_at_cap_skips_extraction_but_still_clusters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits = _process(monkeypatch, used=30, cap=30)
    out = handlers.process({"Records": []})
    assert limits == [] and out["extract"] == {}
    assert out["cluster"] == {"new": 1}


def test_extracted_today_counts_from_utc_midnight(db_session: Session) -> None:
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    assert handlers.extracted_today(db_session, tomorrow) == 0
