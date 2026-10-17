import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


DEFAULT_DATABASE_URL = "sqlite:///./data/demo.sqlite3"


@lru_cache(maxsize=8)
def get_engine(database_url: str | None = None) -> Engine:
    url = database_url or os.getenv("APP_DATABASE_URL", DEFAULT_DATABASE_URL)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine_kwargs = {"poolclass": NullPool} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, **engine_kwargs)


def get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(database_url: str | None = None) -> Iterator[Session]:
    session = get_session_factory(database_url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
