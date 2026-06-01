import os

# Must be set before any app module is imported so lru_cache picks up test values.
os.environ["DATABASE_URL"] = "postgresql://postmint:postmint@localhost:15432/postmint_test"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
os.environ["MORALIS_API_KEY"] = "test-key-fake"

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app

# Clear lru_cache so settings re-read from the env vars set above.
get_settings.cache_clear()

_TEST_DB_URL = "postgresql://postmint:postmint@localhost:15432/postmint_test"
_ADMIN_DB_URL = "postgresql://postmint:postmint@localhost:15432/postmint"

_TABLES_TO_TRUNCATE = "tokens, traits, sales, claims, ingest_jobs"


@pytest.fixture(scope="session")
def test_engine():
    """Create the postmint_test database once per session, build schema, tear down after."""
    admin = create_engine(_ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS postmint_test"))
        conn.execute(text("CREATE DATABASE postmint_test"))
    admin.dispose()

    engine = create_engine(_TEST_DB_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def clean_tables(test_engine):
    """Truncate all tables. Used as a dependency by db/client so each test starts clean."""
    with test_engine.connect() as conn:
        conn.execute(text(f"TRUNCATE {_TABLES_TO_TRUNCATE} RESTART IDENTITY CASCADE"))
        conn.commit()


@pytest.fixture
def db(test_engine, clean_tables) -> Session:
    """Return a live session to the test database. Caller is responsible for commits."""
    TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    session = TestSession()
    yield session
    session.close()


@pytest.fixture
def client(db: Session) -> TestClient:
    """FastAPI TestClient with get_db overridden to use the test session."""
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
