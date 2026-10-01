"""SQLite database setup for the local YT Livestream Chatbot runtime."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import event
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app_paths import DATA_DIRECTORY


DATA_DIR = DATA_DIRECTORY
DATABASE_PATH = DATA_DIR / "yt-livestream-chatbot.sqlite3"


class Base(DeclarativeBase):
    pass


class Database:
    """Owns an engine and session factory so services can be tested in isolation."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        database_url = f"sqlite:///{self.database_path.as_posix()}"
        self.engine = create_engine(database_url, connect_args={"timeout": 30})
        event.listen(self.engine, "connect", _configure_sqlite)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )

    def initialize(self) -> None:
        # Keep directory creation here so RuntimeService can recover to its
        # temporary in-memory mode if an installed folder is not writable.
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(self.engine)


def _configure_sqlite(dbapi_connection: object, _connection_record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
    finally:
        cursor.close()


database = Database(DATABASE_PATH)
