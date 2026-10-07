import re

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, Enum, text

from brokeberg.db.base import Base
from brokeberg.db.models import ENUM_CHECKS
from brokeberg.taxonomy import Topic


def test_upgrade_downgrade_roundtrip(alembic_cfg: Config, db_engine: Engine) -> None:
    command.downgrade(alembic_cfg, "base")
    with db_engine.connect() as conn:
        tables = conn.scalars(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).all()
    assert set(tables) <= {"alembic_version"}
    command.upgrade(alembic_cfg, "head")


def test_models_match_migrations(db_engine: Engine) -> None:
    with db_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_enum_checks_match_taxonomy(db_engine: Engine) -> None:
    """compare_metadata ignores CHECK bodies, so diff each enum CHECK against taxonomy.py."""
    checked = 0
    with db_engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            for col in table.columns:
                if not isinstance(col.type, Enum):
                    continue
                name = f"ck_{table.name}_{col.type.name}"
                definition = conn.scalar(
                    text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
                    {"n": name},
                )
                assert definition is not None, f"missing CHECK {name}"
                in_db = set(re.findall(r"'([^']+)'", definition))
                expected = {m.value for m in ENUM_CHECKS[str(col.type.name)]}
                assert in_db == expected, f"{name}: taxonomy drifted; add a migration"
                checked += 1
    assert checked >= len(ENUM_CHECKS)


def test_event_entities_topic_check_matches_taxonomy(db_engine: Engine) -> None:
    """`event_entities.topic` is a plain CHECK (it also allows ''), so diff it separately."""
    with db_engine.connect() as conn:
        definition = conn.scalar(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
            {"n": "ck_event_entities_topic_valid"},
        )
    assert definition is not None
    in_db = set(re.findall(r"'([^']*)'", definition))
    assert in_db == {t.value for t in Topic} | {""}, "taxonomy drifted; add a migration"
