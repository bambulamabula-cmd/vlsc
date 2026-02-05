from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


DATABASE_URL = f"sqlite:///{settings.sqlite_path}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)




def _run_sqlite_migrations() -> None:
    """Apply lightweight SQLite schema migrations for existing DB files."""
    with engine.begin() as conn:
        if engine.dialect.name != "sqlite":
            return

        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(daily_aggregates)").fetchall()}
        if "latency_samples_total" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE daily_aggregates "
                "ADD COLUMN latency_samples_total INTEGER NOT NULL DEFAULT 0"
            )

def init_db() -> None:
    """Create database tables for all registered models."""
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _run_sqlite_migrations()


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
