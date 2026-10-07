import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Base
from app.main import create_app

# CI also runs the suite against PostgreSQL (and real Redis) via these variables.
TEST_DATABASE_URL = os.environ.get("GEOAPI_TEST_DATABASE_URL")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=TEST_DATABASE_URL or f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        storage_dir=tmp_path / "uploads",
        max_upload_size_mb=1,
        max_extracted_size_mb=5,
        max_archive_members=50,
        redis_url=None,
        frontend_dir=tmp_path / "no-viewer",
    )


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    app = create_app(settings)
    yield app
    # Leave a shared test database (PostgreSQL in CI) empty for the next test.
    Base.metadata.drop_all(app.state.engine)
    app.state.engine.dispose()


@pytest.fixture
def anonymous_client(app: FastAPI) -> Iterator[TestClient]:
    # TestClient runs background tasks before returning the response, so with the in-process
    # dispatcher uploads are fully processed by the time `client.post` returns.
    with TestClient(app) as test_client:
        yield test_client


def create_key(client: TestClient, name: str = "tests") -> str:
    response = client.post("/api/auth/keys/", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["api_key"]


@pytest.fixture
def client(anonymous_client: TestClient) -> TestClient:
    """A client authenticated with a fresh API key."""
    anonymous_client.headers["X-API-Key"] = create_key(anonymous_client)
    return anonymous_client
