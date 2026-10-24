"""Database engine/session setup. SQLite by default, PostgreSQL via DATABASE_URL."""
from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def normalize_database_url(url: str) -> str:
    """Hosting platforms often hand out 'postgres://' URLs that SQLAlchemy rejects."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url



def make_engine(url: str) -> Engine:
    url = normalize_database_url(url)
    if url.startswith("sqlite"):
        from sqlalchemy.engine import make_url

        db_url = make_url(url)
        path = db_url.database

        if path and path != ":memory:":
            folder = os.path.dirname(os.path.abspath(path))
            os.makedirs(folder, exist_ok=True)

        return create_engine(url, connect_args={"check_same_thread": False})

    return create_engine(url, pool_pre_ping=True, pool_recycle=300)

    url = normalize_database_url(url)
    if url.startswith("sqlite"):
        # Make sure the folder exists so the file DB can be created on first start.
        path = url.split("///", 1)[-1]
        folder = os.path.dirname(path)
        if folder and path != ":memory:":
            os.makedirs(folder, exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_recycle=300)


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they do not exist (idempotent; never drops data)."""
    from app import models  # noqa: F401  (register models on Base)

    Base.metadata.create_all(bind=engine)
