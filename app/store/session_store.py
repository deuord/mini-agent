# 会话存储:v1 内存 dict,进程重启即失;v2 视需要加 SQLite 持久化

import time
import uuid


class Session:
    def __init__(self):
        self.session_id = uuid.uuid4().hex
        self.messages: list[dict] = []
        self.updated_at = time.time()

    def append(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        self.updated_at = time.time()


class SessionStore:
    """内存会话存储,TTL 过期后自动清理"""

    def __init__(self, ttl_seconds: int = 3600):
        self._sessions: dict[str, Session] = {}
        self._ttl = ttl_seconds

    def create(self) -> Session:
        session = Session()
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if time.time() - session.updated_at > self._ttl:
            del self._sessions[session_id]
            return None
        return session


_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store
