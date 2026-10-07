"""SQLAlchemy 2.0 engine + session factory, with pgvector registered on every connection.

The engine is built lazily so importing this module never touches the database.
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
def get_engine() -> Engine:
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
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
