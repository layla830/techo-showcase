from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from .config import Settings


class Database:
    def __init__(self, settings: Settings):
        self.path = settings.database_path
        self.engine = create_engine(
            URL.create("sqlite", database=str(self.path)),
            connect_args={"check_same_thread": False, "timeout": 10},
            hide_parameters=True,
        )

        @event.listens_for(self.engine, "connect")
        def configure(dbapi_connection, connection_record):
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        @event.listens_for(self.engine, "begin")
        def begin(connection):
            # Writers reserve the SQLite lock before checking deduplication or order.
            statement = (
                "BEGIN IMMEDIATE" if connection.get_execution_options().get("techo_write") else "BEGIN"
            )
            connection.exec_driver_sql(statement)

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.path.exists():
            self.path.touch(mode=0o600, exist_ok=False)
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
        with self.engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[Session]:
        engine = self.engine.execution_options(techo_write=write)
        with Session(engine, expire_on_commit=False) as session:
            with session.begin():
                yield session

    def close(self) -> None:
        self.engine.dispose()
