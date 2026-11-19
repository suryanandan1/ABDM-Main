from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.database import Base
from init_db import BASELINE_REVISION, migrate


def _engine(tmp_path: Path, name: str):
    engine = create_engine(f"sqlite:///{(tmp_path / name).as_posix()}")
    return engine


def test_migrations_match_models(tmp_path):
    engine = _engine(tmp_path, "fresh.db")
    migrate(engine)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) is not None
    migrate(engine)
    engine.dispose()


def test_pre_migration_database_is_upgraded(tmp_path):
    engine = _engine(tmp_path, "legacy.db")
    migrate(engine)
    config = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    config.attributes["configure_logger"] = False
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, BASELINE_REVISION)
        connection.execute(text("DROP TABLE alembic_version"))
        connection.execute(text("INSERT INTO hospitals (id, name, code, is_active, created_at) "
                                "VALUES (1, 'Old Hospital', 'OLD', 1, '2026-01-01')"))
    migrate(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("users")}
    assert {"token_version", "mfa_enabled"} <= columns
    assert {"user_sessions", "login_failures"} <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM hospitals WHERE id = 1")) == "Old Hospital"
    engine.dispose()
