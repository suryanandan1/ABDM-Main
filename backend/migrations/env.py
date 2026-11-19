from logging.config import fileConfig

from alembic import context

from app import models
from app.database import engine, is_sqlite

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = models.Base.metadata
options = {"target_metadata": target_metadata, "render_as_batch": is_sqlite, "compare_type": True}


def run_migrations_offline() -> None:
    context.configure(url=str(engine.url), literal_binds=True, dialect_opts={"paramstyle": "named"}, **options)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, **options)
        with context.begin_transaction():
            context.run_migrations()
        return
    with engine.connect() as connection:
        if is_sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        context.configure(connection=connection, **options)
        with context.begin_transaction():
            context.run_migrations()
        if is_sqlite:
            broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
            if broken:
                raise RuntimeError(f"Migration left broken references: {broken[:5]}")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
