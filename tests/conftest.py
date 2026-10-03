# Test setup. We don't need real Postgres, Redis or Gemini for tests:
#   - SQLite file instead of PostgreSQL
#   - fakeredis (an in-memory fake Redis) instead of Redis
#   - LLM_PROVIDER=mock instead of Gemini
# Environment variables must be set BEFORE the app is imported.

import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["JWT_SECRET"] = "test-secret-key-that-is-at-least-32-bytes-long"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["RATE_LIMIT_PER_MINUTE"] = "5"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["USER_PASSWORD"] = "alice123"
os.environ["READONLY_PASSWORD"] = "viewer123"

import fakeredis  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import cache, llm  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def clean_database():
    if os.path.exists("test.db"):
        os.remove("test.db")
    yield
    if os.path.exists("test.db"):
        os.remove("test.db")


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache, "redis_client", fake)
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)  # don't really wait during retries
    return fake


@pytest.fixture
def client():
    with TestClient(app) as test_client:  # "with" runs the startup code (tables + demo users)
        yield test_client


def get_token(client, username, password):
    response = client.post("/auth/login", json={"username": username, "password": password})
    return response.json()["access_token"]


@pytest.fixture
def user_headers(client):
    return {"Authorization": f"Bearer {get_token(client, 'alice', 'alice123')}"}


@pytest.fixture
def admin_headers(client):
    return {"Authorization": f"Bearer {get_token(client, 'admin', 'admin123')}"}


@pytest.fixture
def readonly_headers(client):
    return {"Authorization": f"Bearer {get_token(client, 'viewer', 'viewer123')}"}
