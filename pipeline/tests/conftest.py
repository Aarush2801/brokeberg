import os

# Tests never touch the network: the embedding model must come from the local HF cache.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["EMBED_PROVIDER"] = "local"
os.environ["LLM_PROVIDER"] = "anthropic"

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import Engine, create_engine, make_url, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from brokeberg.config import get_settings  # noqa: E402
from brokeberg.ids.resolve import clear_cache  # noqa: E402

TEST_DB_NAME = "brokeberg_test"
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ensure_test_database() -> str:
    """Create `brokeberg_test` next to the dev DB (never touching dev data); return its URL."""
    dev_url = make_url(get_settings().database_url)
    admin = create_engine(dev_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB_NAME}
            )
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    except OperationalError:
        pytest.skip("Postgres is not reachable; run `make up`")
    finally:
        admin.dispose()
    return dev_url.set(database=TEST_DB_NAME).render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def alembic_cfg() -> Iterator[Config]:
    """Alembic pointed at the test database (env.py reads DATABASE_URL via settings)."""
    get_settings.cache_clear()
    url = _ensure_test_database()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    yield Config(str(ALEMBIC_INI))
    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous


@pytest.fixture(scope="session")
def db_engine(alembic_cfg: Config) -> Iterator[Engine]:
    command.upgrade(alembic_cfg, "head")
    engine = create_engine(os.environ["DATABASE_URL"])
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session inside an outer transaction that is always rolled back."""
    with db_engine.connect() as conn:
        trans = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            trans.rollback()
            clear_cache()


# --- extraction: stubbed LLM -----------------------------------------------------------------


class FakeLLM:
    """Stands in for `llm.complete`: returns a canned response per output schema, records calls.

    A response may be a pydantic instance, or a callable `(prompt) -> instance`.
    """

    def __init__(self) -> None:
        self.responses: dict[type, Any] = {}
        self.calls: list[tuple[type | None, str, str | None]] = []

    def set(self, schema: type, response: Any) -> None:
        self.responses[schema] = response

    def __call__(self, prompt: str, *, schema: type | None = None, **kwargs: Any) -> Any:
        self.calls.append((schema, prompt, kwargs.get("model")))
        if schema not in self.responses:
            raise AssertionError(f"unexpected LLM call for {schema}")
        r = self.responses[schema]
        return r(prompt) if callable(r) else r

    def schemas_called(self) -> list[type | None]:
        return [c[0] for c in self.calls]


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    from brokeberg import llm

    fake = FakeLLM()
    monkeypatch.setattr(llm, "complete", fake)
    return fake


@pytest.fixture
def seeded_db(db_session: Session) -> Session:
    from brokeberg.db.seed import seed

    seed(db_session)
    return db_session
