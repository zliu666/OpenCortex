"""In-memory session manager for multi-turn conversations."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from opencortex.ui.runtime import RuntimeBundle


@dataclass
class Session:
    id: str
    bundle: RuntimeBundle
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)


class SessionManager:
    """Manages active sessions in memory."""

    def __init__(self, max_sessions: int = 100, ttl_seconds: int = 3600) -> None:
        self._sessions: dict[str, Session] = {}
        self._max_sessions = max_sessions
        self._ttl = ttl_seconds

    def create(self, bundle: RuntimeBundle) -> Session:
        self._evict()
        session_id = uuid.uuid4().hex[:16]
        session = Session(id=session_id, bundle=bundle)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id)
        if session:
            session.last_active = time.time()
        return session

    def remove(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    def _evict(self) -> None:
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s.last_active > self._ttl
        ]
        for sid in expired:
            self._sessions.pop(sid, None)
        # If still at capacity, remove oldest
        while len(self._sessions) >= self._max_sessions:
            oldest_id = min(self._sessions, key=lambda k: self._sessions[k].last_active)
            self._sessions.pop(oldest_id)
