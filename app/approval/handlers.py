from __future__ import annotations

import structlog
from aiogram.types import Message

from app.agents.cmo_agent_service import CMOAgentService
from app.approval.session_store import SessionStore

log = structlog.get_logger()


async def cmd_new(message: Message, cmo_sessions: SessionStore) -> None:
    """Create a fresh conversation thread for this chat."""
    thread_id = cmo_sessions.new_session(message.chat.id)
    log.info("new_session_created", chat_id=message.chat.id, thread_id=thread_id)
    await message.reply("Новая сессия начата. Можешь писать!")


async def handle_message(
    message: Message,
    cmo: CMOAgentService,
    cmo_sessions: SessionStore,
) -> None:
    """Forward user message to CMO Agent and reply with the response."""
    thread_id = cmo_sessions.get_or_create(message.chat.id)
    log.info("message_received", chat_id=message.chat.id, thread_id=thread_id, text=message.text)

    chunks: list[str] = []
    async for token in cmo.run(thread_id, message.text or ""):
        chunks.append(token)

    response = "".join(chunks).strip() or "..."
    await message.answer(response)
