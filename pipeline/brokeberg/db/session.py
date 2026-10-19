"""SQLAlchemy 2.0 engine + session factory, with pgvector registered on every connection.

The engine is built lazily so importing this module never touches the database.

With DB_IAM_AUTH (prod: Aurora express configuration, which only accepts IAM auth), every new
connection gets a fresh RDS IAM token as its password. Tokens live 15 minutes but are only
checked at connect time, so pooled connections outlive them.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from pgvector.psycopg import register_vector
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from brokeberg.config import get_settings


def _register_pgvector(dbapi_connection: Any, _record: Any) -> None:
    # Requires the `vector` extension, which the baseline migration creates.
    register_vector(dbapi_connection)


@lru_cache
def _rds_client() -> Any:
    import boto3

    return boto3.client("rds", region_name=get_settings().require("aws_region"))


def iam_token(host: str, port: int, user: str) -> str:
    """A signed RDS IAM auth token (computed locally; no AWS call)."""
    return str(_rds_client().generate_db_auth_token(DBHostname=host, Port=port, DBUsername=user))


def use_iam_auth(engine: Engine) -> None:
    """Sign every new connection with an IAM token instead of a stored password."""
    url = engine.url

    def _token(_dialect: Any, _record: Any, _cargs: Any, cparams: dict[str, Any]) -> None:
        cparams["password"] = iam_token(str(url.host), url.port or 5432, str(url.username))

    event.listen(engine, "do_connect", _token)


@lru_cache
def get_engine() -> Engine:
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    if get_settings().db_iam_auth:
        use_iam_auth(engine)
    event.listen(engine, "connect", _register_pgvector)
    return engine


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on error."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
