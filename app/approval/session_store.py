from __future__ import annotations

from uuid import uuid4


class SessionStore:
    """In-memory per-chat thread_id registry."""

    def __init__(self) -> None:
        self._sessions: dict[int, str] = {}

    def get_or_create(self, chat_id: int) -> str:
        if chat_id not in self._sessions:
            self._sessions[chat_id] = str(uuid4())
        return self._sessions[chat_id]

    def new_session(self, chat_id: int) -> str:
        thread_id = str(uuid4())
        self._sessions[chat_id] = thread_id
        return thread_id
