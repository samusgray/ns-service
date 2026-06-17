import os

import pytest
from sqlalchemy import text

from notification_service.db import Base, make_engine, make_session_factory

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://sg@localhost:5432/notification_service_test",
)

# The app builds its engine from DATABASE_URL at import time; point it at the test DB
# so importing the app during integration tests never touches a dev/prod database.
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)


@pytest.fixture(scope="session")
def engine():
    eng = make_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    factory = make_session_factory(engine)
    s = factory()
    s.execute(text("TRUNCATE notifications"))
    s.commit()
    try:
        yield s
    finally:
        s.close()
