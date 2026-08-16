import os

# Must be set before any app module is imported so lru_cache picks up test values.
os.environ["DATABASE_URL"] = "postgresql://postmint:postmint@localhost:15432/postmint_test"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
os.environ["MORALIS_API_KEY"] = "test-key-fake"
# Force the OpenSea listings layer OFF regardless of the developer's .env —
# gallery tests must never hit the real API (they monkeypatch instead).
os.environ["OPENSEA_API_KEY"] = ""
# Disable the standings/directory rollup cache so directly-seeded rows are
# always visible; cache behavior itself is covered by test_ttl_cache.py.
os.environ["STANDINGS_CACHE_TTL_SECONDS"] = "0"

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

_TABLES_TO_TRUNCATE = "tokens, traits, sales, claims, ingest_jobs, transfer_sync, seasons, claim_nonces, collections, manifests"


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
    from app.ttl_cache import race_cache

    race_cache.clear()
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
def mock_chain(monkeypatch):
    """Stub on-chain verification so `/claim/confirm` accepts a test tx and
    reports slot 1 (the real path fetches an eth_getTransactionReceipt)."""
    from app.api import claims as claims_mod

    def _stub(*_a, **_k):
        return {"slot_number": 1, "nonce": 1, "window_started_at": 0}

    monkeypatch.setattr(claims_mod, "verify_claim_tx", _stub)
    return _stub


@pytest.fixture
def client(db: Session) -> TestClient:
    """FastAPI TestClient with get_db overridden to use the test session."""
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
