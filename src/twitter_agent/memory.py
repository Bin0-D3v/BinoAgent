from __future__ import annotations

from typing import List, Optional

from . import db


def remember(key: str, value: str) -> db.MemoryEntry:
    return db.add_memory(key=key, value=value)


def recall(limit: Optional[int] = None) -> List[db.MemoryEntry]:
    return list(db.list_memory(limit=limit))


def remember_if_new(key: str, value: str) -> db.MemoryEntry:
    with db.session_scope() as session:
        existing = (
            session.query(db.MemoryEntry)
            .filter(db.MemoryEntry.key == key, db.MemoryEntry.value == value)
            .order_by(db.MemoryEntry.created_at.desc())
            .first()
        )
        if existing:
            return existing
        entry = db.MemoryEntry(key=key, value=value)
        session.add(entry)
        session.flush()
        return entry
