from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import make_engine, make_session_factory
from ..providers import StubSender
from ..repository import SqlNotificationRepository
from ..service import NotificationService

engine = make_engine(get_settings().database_url)
SessionFactory = make_session_factory(engine)


def get_session() -> Iterator[Session]:
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


def get_service(session: Session = Depends(get_session)) -> NotificationService:
    return NotificationService(SqlNotificationRepository(session), StubSender())
