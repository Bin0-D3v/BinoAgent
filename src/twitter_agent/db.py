from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DB_PATH = Path(os.getenv("AGENT_DB_PATH", "./data/agent.db"))


class Base(DeclarativeBase):
    pass


class MemoryEntry(Base):
    __tablename__ = "memory_entries"

    id = Column(Integer, primary_key=True)
    key = Column(String(128), nullable=False)
    value = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class TweetRecord(Base):
    __tablename__ = "tweet_records"

    id = Column(Integer, primary_key=True)
    content = Column(Text, nullable=False)
    topic = Column(String(128), nullable=True)
    model = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


def _ensure_db_dir(db_path: Path) -> None:
    if not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)


def get_engine(db_path: Optional[Path] = None):
    resolved_path = db_path or DEFAULT_DB_PATH
    _ensure_db_dir(resolved_path)
    engine_url = f"sqlite:///{resolved_path.resolve()}"
    return create_engine(engine_url, future=True)


engine = get_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def add_memory(key: str, value: str) -> MemoryEntry:
    with session_scope() as session:
        entry = MemoryEntry(key=key, value=value)
        session.add(entry)
        session.flush()
        return entry


def list_memory(limit: Optional[int] = None) -> Iterable[MemoryEntry]:
    with session_scope() as session:
        query = session.query(MemoryEntry).order_by(MemoryEntry.created_at.desc())
        if limit:
            query = query.limit(limit)
        return list(reversed(query.all()))


def add_tweet(content: str, topic: Optional[str], model: Optional[str]) -> TweetRecord:
    with session_scope() as session:
        record = TweetRecord(content=content, topic=topic, model=model)
        session.add(record)
        session.flush()
        return record

