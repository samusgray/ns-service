from collections.abc import Iterator

from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import make_engine, make_session_factory

engine = make_engine(get_settings().database_url)
SessionFactory = make_session_factory(engine)


def get_session() -> Iterator[Session]:
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
