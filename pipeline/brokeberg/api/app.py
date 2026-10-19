"""The terminal's query API. Each endpoint calls one Day-5 rollup view and returns it unchanged,
so provenance (source URL + span + trust tier) and confidence reach the UI on every row.

The web app proxies `/api/*` here; nothing in this module writes to the database.
"""

import hmac
from collections.abc import Iterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from brokeberg.api import refs
from brokeberg.api.rsch import QueryResponse, answer
from brokeberg.config import get_settings
from brokeberg.db.models import Entity
from brokeberg.db.session import get_sessionmaker
from brokeberg.graph import views

app = FastAPI(title="Brokeberg query API")


def get_session() -> Iterator[Session]:
    """A request-scoped session that never commits."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


DB = Depends(get_session)

QUERY_SECRET_HEADER = "x-brokeberg-query-key"


def require_query_secret(
    key: str | None = Header(default=None, alias=QUERY_SECRET_HEADER),
) -> None:
    """Gate the LLM-spending endpoint behind a shared secret only the web app's server holds."""
    secret = get_settings().query_secret
    if secret and not (key and hmac.compare_digest(key, secret)):
        raise HTTPException(status_code=403, detail="forbidden")


@app.exception_handler(refs.Direction)
def _direction(_: Request, exc: refs.Direction) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"detail": exc.message, "options": [o.model_dump() for o in exc.options]},
    )


class FeedResponse(BaseModel):
    window_days: float
    rows: list[views.FeedRow]


class StanceResponse(BaseModel):
    entity: views.EntityInfo
    topic: str
    rows: list[views.StanceRow]


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.get("/api/feed")
def feed(limit: int = 50, session: Session = DB) -> FeedResponse:
    return FeedResponse(
        window_days=get_settings().feed_window_days,
        rows=views.feed(session, limit=min(max(limit, 1), 200)),
    )


@app.get("/api/event/{ref}")
def event(ref: str, session: Session = DB) -> views.EventObjectView:
    return views.event_object(session, refs.event_id(session, ref))


@app.get("/api/race/{ref}")
def race(ref: str, session: Session = DB) -> views.RaceDossier:
    return views.race_dossier(session, refs.race_id(session, ref))


@app.get("/api/entity/{ref}")
def entity(ref: str, session: Session = DB) -> views.EntityDossier:
    return views.entity_dossier(session, refs.entity_id(session, ref))


@app.get("/api/stance")
def stance(entity: str, topic: str, session: Session = DB) -> StanceResponse:
    entity_id = refs.entity_id(session, entity)
    t = refs.topic(topic, command_prefix=f"STANCE {entity_id} ")
    ent = session.get(Entity, entity_id)
    assert ent is not None
    return StanceResponse(
        entity=views.EntityInfo(
            entity_id=ent.id, canonical_id=ent.canonical_id, name=ent.name,
            entity_type=ent.entity_type,
        ),
        topic=t.value,
        rows=views.stance_timeline(session, entity_id, t.value),
    )


@app.get("/api/indicators")
def indicators(session: Session = DB) -> list[views.TickerRow]:
    return views.ticker(session)


@app.post("/api/query", dependencies=[Depends(require_query_secret)])
def query(body: QueryRequest, session: Session = DB) -> QueryResponse:
    return answer(session, body.question)
