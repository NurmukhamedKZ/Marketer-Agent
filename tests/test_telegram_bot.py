"""Tests for Telegram bot session store and handlers."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.approval.session_store import SessionStore


# ── SessionStore unit tests ────────────────────────────────────────────────────


def test_get_or_create_returns_new_thread_id_for_unknown_chat() -> None:
    store = SessionStore()
    thread_id = store.get_or_create(chat_id=123)
    assert isinstance(thread_id, str)
    assert len(thread_id) > 0


def test_get_or_create_returns_same_thread_id_for_known_chat() -> None:
    store = SessionStore()
    first = store.get_or_create(chat_id=123)
    second = store.get_or_create(chat_id=123)
    assert first == second


def test_new_session_returns_different_thread_id_each_call() -> None:
    store = SessionStore()
    first = store.new_session(chat_id=123)
    second = store.new_session(chat_id=123)
    assert first != second


def test_new_session_replaces_existing_session() -> None:
    store = SessionStore()
    old = store.get_or_create(chat_id=123)
    new = store.new_session(chat_id=123)
    assert store.get_or_create(chat_id=123) == new
    assert new != old


def test_sessions_are_isolated_per_chat() -> None:
    store = SessionStore()
    t1 = store.get_or_create(chat_id=1)
    t2 = store.get_or_create(chat_id=2)
    assert t1 != t2


# ── Handler tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cmd_new_creates_new_session_and_replies() -> None:
    from app.approval.handlers import cmd_new

    store = SessionStore()
    old_id = store.get_or_create(42)

    message = AsyncMock()
    message.chat.id = 42
    message.reply = AsyncMock()

    await cmd_new(message, store)

    new_id = store.get_or_create(42)
    assert old_id != new_id
    message.reply.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_collects_and_sends_cmo_response() -> None:
    from app.approval.handlers import handle_message

    store = SessionStore()

    async def fake_run(thread_id: str, text: str):  # type: ignore[misc]
        yield "Hello"
        yield " world"

    cmo = MagicMock()
    cmo.run = fake_run

    message = AsyncMock()
    message.chat.id = 42
    message.text = "test question"
    message.answer = AsyncMock()

    await handle_message(message, cmo, store)

    message.answer.assert_called_once_with("Hello world")


@pytest.mark.asyncio
async def test_handle_message_creates_session_if_missing() -> None:
    from app.approval.handlers import handle_message

    store = SessionStore()

    captured_thread_ids: list[str] = []

    async def fake_run(thread_id: str, text: str):  # type: ignore[misc]
        captured_thread_ids.append(thread_id)
        yield "ok"

    cmo = MagicMock()
    cmo.run = fake_run

    message = AsyncMock()
    message.chat.id = 99
    message.text = "hi"
    message.answer = AsyncMock()

    await handle_message(message, cmo, store)

    assert len(captured_thread_ids) == 1
    assert isinstance(captured_thread_ids[0], str)


@pytest.mark.asyncio
async def test_handle_message_uses_same_session_across_turns() -> None:
    from app.approval.handlers import handle_message

    store = SessionStore()

    captured_thread_ids: list[str] = []

    async def fake_run(thread_id: str, text: str):  # type: ignore[misc]
        captured_thread_ids.append(thread_id)
        yield "ok"

    cmo = MagicMock()
    cmo.run = fake_run

    message = AsyncMock()
    message.chat.id = 77
    message.text = "first"
    message.answer = AsyncMock()

    await handle_message(message, cmo, store)
    await handle_message(message, cmo, store)

    assert captured_thread_ids[0] == captured_thread_ids[1]
