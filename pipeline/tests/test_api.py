import re
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from cluster_corpus import CPI_BLS, MURKOWSKI, unit_vec
from conftest import FakeLLM
from fastapi.testclient import TestClient
from graph_corpus import GA, build_graph
from sqlalchemy import select
from sqlalchemy.orm import Session

from brokeberg.api import rsch
from brokeberg.api.app import app, get_session
from brokeberg.api.rsch import Claim, RschAnswer
from brokeberg.config import get_settings
from brokeberg.db.models import EMBED_DIM, Event, EventEmbedding, Indicator


@pytest.fixture
def graph(seeded_db: Session, monkeypatch: pytest.MonkeyPatch) -> dict[str, Event]:
    # The corpus is dated September 2026; widen the feed window so it is in view today.
    monkeypatch.setenv("FEED_WINDOW_DAYS", "3650")
    get_settings.cache_clear()
    return build_graph(seeded_db)


@pytest.fixture
def client(seeded_db: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: seeded_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def assert_conf(x: Any) -> None:
    assert isinstance(x, float) and 0.0 <= x <= 1.0


# --- contract ----------------------------------------------------------------------------------


def test_feed_rows_carry_provenance(client: TestClient, graph: dict[str, Event]) -> None:
    body = client.get("/api/feed").json()
    assert body["window_days"] == 3650
    assert {r["event_id"] for r in body["rows"]} >= {graph["cpi"].id, graph["nomination"].id}
    for r in body["rows"]:
        assert r["source_url"] and r["span"] and r["trust_tier"]
        assert r["headline"] and r["source_count"] >= 1 and isinstance(r["topics"], list)
        assert_conf(r["confidence"])


def test_event_object(client: TestClient, graph: dict[str, Event]) -> None:
    head = graph["cpi"].id
    body = client.get(f"/api/event/E{head}").json()
    assert client.get(f"/api/event/{head}").json() == body
    assert body["id"] == head and body["headline"]
    assert_conf(body["confidence"])
    assert {s["url"] for s in body["sources"]} >= {CPI_BLS.url}
    for s in body["sources"]:
        assert s["url"] and s["span"]
    [reaction] = body["political_reactions"]
    assert reaction["canonical_id"] == MURKOWSKI and reaction["span"] and reaction["source_url"]
    assert reaction["flip"]["prior_event_id"] == graph["earlier"].id
    [ga] = [e for e in body["affected_elections"] if e["race_id"] == GA]
    assert ga["rationale"]
    assert_conf(ga["confidence"])


def test_race_dossier(client: TestClient, graph: dict[str, Event]) -> None:
    body = client.get("/api/race/ga-sen").json()
    assert body["race_id"] == GA and body["rating"] == "tossup"
    assert body["rating_history"][0]["source_url"]
    assert body["poll_average"]["source_url"]
    assert body["linked_events"]
    for e in body["linked_events"]:
        assert e["source_url"] and e["span"] and e["rationale"]
        assert_conf(e["confidence"])


def test_entity_dossier_by_name(client: TestClient, graph: dict[str, Event]) -> None:
    body = client.get("/api/entity/MURKOWSKI").json()
    assert body["entity"]["canonical_id"] == MURKOWSKI
    assert client.get(f"/api/entity/{MURKOWSKI}").json() == body
    for s in body["stances"]:
        assert s["span"] and s["source_url"]
        assert_conf(s["confidence"])
    for e in body["recent_events"]:
        assert e["source_url"] and e["span"]
    for r in body["relationships"]:
        assert r["source_url"] and r["span"]


def test_stance_timeline(client: TestClient, graph: dict[str, Event]) -> None:
    body = client.get("/api/stance", params={"entity": "Murkowski", "topic": "INFLATION"}).json()
    assert body["entity"]["canonical_id"] == MURKOWSKI
    assert body["topic"] == "inflation_cost_of_living"
    assert [r["stance"] for r in body["rows"]] == ["support", "oppose"]
    for r in body["rows"]:
        assert r["span"] and r["source_url"]
        assert_conf(r["confidence"])


def test_indicators(client: TestClient, seeded_db: Session) -> None:
    for asof, value in ((date(2026, 8, 1), "4.1"), (date(2026, 9, 1), "4.2")):
        seeded_db.add(Indicator(series_id="UNRATE", asof=asof, source="fred", value=Decimal(value)))
    seeded_db.flush()
    [row] = client.get("/api/indicators").json()
    assert (row["series_id"], row["value"], row["asof"]) == ("UNRATE", 4.2, "2026-09-01")
    assert row["source_url"] and row["span"]


# --- directions --------------------------------------------------------------------------------


def test_unknown_refs_give_directions(client: TestClient, graph: dict[str, Event]) -> None:
    r = client.get("/api/race/ZZ-SEN")
    assert r.status_code == 404
    assert any(o["command"] == f"RACE {GA}" for o in r.json()["options"])

    r = client.get("/api/event/E999999")
    assert r.status_code == 404 and "FEED" in r.json()["detail"]

    r = client.get("/api/stance", params={"entity": "MURKOWSKI", "topic": "POLICY"})
    assert r.status_code == 409
    labels = {o["label"] for o in r.json()["options"]}
    assert labels == {"monetary_policy", "foreign_policy_defense"}

    r = client.get("/api/entity/NOBODYXYZ")
    assert r.status_code in (404, 409)
    assert all(o["command"].startswith("ENT ") for o in r.json()["options"])


# --- RSCH --------------------------------------------------------------------------------------

QUESTION_VEC = unit_vec(1.0, 1)


@pytest.fixture
def embedded(
    seeded_db: Session, graph: dict[str, Event], monkeypatch: pytest.MonkeyPatch
) -> dict[str, Event]:
    """CPI members close to the question vector, the nomination far from it."""
    near = {graph["cpi"].id, graph["earlier"].id}
    for i, m in enumerate(seeded_db.scalars(select(Event).where(Event.cluster_id != Event.id))):
        vec = unit_vec(0.9 if m.cluster_id in near else 0.1, 2 + i % (EMBED_DIM - 2))
        seeded_db.add(EventEmbedding(event_id=m.id, embedding=vec, embed_model="fixture"))
    seeded_db.flush()
    monkeypatch.setattr(rsch, "embed", lambda texts: [QUESTION_VEC for _ in texts])
    return graph


def record_numbers(prompt: str) -> dict[int, str]:
    return {int(n): line for n, line in re.findall(r"^\[(\d+)\] (.*)$", prompt, re.MULTILINE)}


def bls_record(prompt: str) -> int:
    return next(n for n, line in record_numbers(prompt).items() if "0.4 percent" in line)


def ask(client: TestClient, question: str) -> dict[str, Any]:
    r = client.post("/api/query", json={"question": question})
    assert r.status_code == 200
    body: dict[str, Any] = r.json()
    return body


def test_rsch_keeps_grounded_claims_and_drops_the_rest(
    client: TestClient, embedded: dict[str, Event], fake_llm: FakeLLM
) -> None:
    fake_llm.set(RschAnswer, lambda prompt: RschAnswer(insufficient=False, claims=[
        Claim(text="CPI rose 0.4 percent in August.", cited=[bls_record(prompt)]),
        Claim(text="CPI rose 0.9 percent in August.", cited=[bls_record(prompt)]),
        Claim(text="Prices rose in August.", cited=[]),
    ]))
    body = ask(client, "what happened with consumer prices in August?")

    assert body["refused"] is False
    [claim] = body["claims"]
    assert claim["text"] == "CPI rose 0.4 percent in August."
    assert {d["text"] for d in body["dropped_claims"]} == {
        "CPI rose 0.9 percent in August.", "Prices rose in August.",
    }
    # Every claim maps to returned sources, and every source to a retrieved event object.
    numbers = {s["n"] for s in body["sources"]}
    assert set(claim["cited"]) <= numbers
    assert {s["event_id"] for s in body["sources"]} <= {
        embedded["cpi"].id, embedded["earlier"].id
    }
    assert all(s["url"] and s["span"] for s in body["sources"])
    # One of three claims survived: confidence is scaled down accordingly.
    assert 0.0 < body["confidence"] <= 1 / 3


def test_rsch_prompt_holds_only_retrieved_records(
    client: TestClient, embedded: dict[str, Event], fake_llm: FakeLLM
) -> None:
    fake_llm.set(RschAnswer, RschAnswer(insufficient=True, claims=[]))
    body = ask(client, "what happened with consumer prices in August?")
    [(_, prompt, _)] = fake_llm.calls
    assert len(record_numbers(prompt)) == len(body["sources"])
    assert "nomination" not in prompt.lower().split("<records>")[1]


def test_rsch_refuses_when_model_says_insufficient(
    client: TestClient, embedded: dict[str, Event], fake_llm: FakeLLM
) -> None:
    fake_llm.set(RschAnswer, RschAnswer(insufficient=True, claims=[]))
    body = ask(client, "who will win the Georgia race?")
    assert body["refused"] is True and body["claims"] == [] and body["confidence"] == 0.0
    assert body["message"] == rsch.REFUSAL


def test_rsch_refuses_when_no_claim_is_grounded(
    client: TestClient, embedded: dict[str, Event], fake_llm: FakeLLM
) -> None:
    fake_llm.set(RschAnswer, RschAnswer(insufficient=False, claims=[
        Claim(text="CPI rose 0.4 percent in August.", cited=[999]),
        Claim(text="Inflation hit 7 percent.", cited=[1]),
    ]))
    body = ask(client, "what happened with consumer prices in August?")
    assert body["refused"] is True and body["claims"] == []
    assert len(body["dropped_claims"]) == 2


def test_rsch_without_records_never_calls_the_model(
    client: TestClient, graph: dict[str, Event], fake_llm: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rsch, "embed", lambda texts: [QUESTION_VEC for _ in texts])  # no rows
    body = ask(client, "what is the weather on mars?")
    assert body["refused"] is True and body["sources"] == []
    assert fake_llm.calls == []
