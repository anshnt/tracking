"""SQLAlchemy 2 engine/session. Handlers commit explicitly; get_db only closes."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from portal.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def session_factory() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency. Caller does db.commit(); uncommitted work is rolled back on close."""
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
