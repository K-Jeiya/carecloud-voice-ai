"""Test fixtures: an isolated in-memory SQLite DB per test, wired in via dependency override."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")  # must be set before app import
os.environ["API_KEY"] = ""
os.environ["VAPI_SERVER_SECRET"] = ""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    from app import models  # noqa: F401

    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture()
def client(session_factory):
    def _get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def valid_payload() -> dict:
    return {
        "first_name": "Jane",
        "last_name": "Synthetic",
        "date_of_birth": "03/04/1990",
        "sex": "Female",
        "phone_number": "(202) 555-0101",
        "address_line_1": "100 Demo Street",
        "city": "Springfield",
        "state": "il",
        "zip_code": "62701",
    }
