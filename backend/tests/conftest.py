from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Keep tests isolated from local .env provider keys.
os.environ.setdefault("AI_USE_STUB", "1")

# Keep tests isolated from development database.
TEST_RUNS_DIR = ROOT / "test_runs"
TEST_RUNS_DIR.mkdir(parents=True, exist_ok=True)
test_database_url = os.getenv("TEST_DATABASE_URL", f"sqlite:///{TEST_RUNS_DIR / 'test.db'}")
os.environ["DATABASE_URL"] = test_database_url
if "service.db" in test_database_url:
    raise RuntimeError("Refusing to run tests against service.db. Use TEST_DATABASE_URL for an isolated test DB.")

from app.db.database import Base, engine, init_db
from app.main import app


def _alembic_config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def reset_schema_via_alembic() -> None:
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    command.upgrade(_alembic_config(), "head")


@pytest.fixture(autouse=True)
def _force_stub_agents() -> None:
    os.environ.setdefault("AI_USE_STUB", "1")


@pytest.fixture(autouse=True)
def reset_db() -> None:
    init_db()
    reset_schema_via_alembic()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
