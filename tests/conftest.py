import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("ENABLE_NOTION_SYNC", "false")

from db import Base, get_db  # noqa: E402


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite:///{db_path.as_posix()}"


def _make_engine(db_path: Path) -> Engine:
    return create_engine(
        _sqlite_url(db_path),
        connect_args={"check_same_thread": False},
    )


def _make_override_get_db(
    session_factory: sessionmaker,
) -> Callable[..., Generator[Session, None, None]]:
    def override_get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    return override_get_db


def bind_test_db(app: FastAPI, session_factory: sessionmaker) -> Callable[[], None]:
    """Override get_db on app. Returns a cleanup callable."""
    app.dependency_overrides[get_db] = _make_override_get_db(session_factory)

    def cleanup() -> None:
        app.dependency_overrides.pop(get_db, None)

    return cleanup


@contextmanager
def isolated_app_db(app: FastAPI, tmp_path: Path):
    """Create a temp SQLite DB, bind overrides on app, tear down on exit."""
    db_file = tmp_path / "test.db"
    engine = _make_engine(db_file)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    cleanup = bind_test_db(app, factory)
    try:
        yield factory
    finally:
        cleanup()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def test_engine(tmp_path: Path) -> Generator[Engine, None, None]:
    db_file = tmp_path / "test.db"
    engine = _make_engine(db_file)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def test_session_factory(test_engine: Engine) -> sessionmaker:
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def db_session(test_session_factory: sessionmaker) -> Generator[Session, None, None]:
    session = test_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(test_session_factory: sessionmaker) -> Generator[TestClient, None, None]:
    from main import app

    cleanup = bind_test_db(app, test_session_factory)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        cleanup()
