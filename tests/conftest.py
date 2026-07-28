import os
import tempfile

import pytest
from fastapi.testclient import TestClient

# DATA_DIR doit être fixé avant tout import de app.core.db : le moteur SQLAlchemy
# est créé une seule fois au niveau module et resterait sinon lié au premier
# chemin rencontré pendant la session de tests.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="omp_tests_")
os.environ["DATA_DIR"] = _TEST_DATA_DIR

from app.core.db import Base, async_session_maker, engine  # noqa: E402


@pytest.fixture(scope="session")
def _app_client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client(_app_client):
    yield _app_client


@pytest.fixture()
async def db_session():
    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
async def _clean_tables(_app_client):
    yield
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
