from __future__ import annotations

import asyncio

import structlog
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.agents.cmo_agent_service import CMOAgentService
from app.agents.x_sub_agent_service import XSubAgentService
from app.approval.handlers import cmd_new, handle_message
from app.approval.session_store import SessionStore
from app.config import get_settings
from app.db.pool import get_pool
from app.db.setup import ensure_seed_data
from app.logging_setup import setup_logging

log = structlog.get_logger()

router = Router()


@router.message(Command("new"))
async def _cmd_new(message: Message, cmo_sessions: SessionStore) -> None:
    await cmd_new(message, cmo_sessions)


@router.message(F.text)
async def _handle_message(
    message: Message,
    cmo: CMOAgentService,
    cmo_sessions: SessionStore,
    x_subagent: XSubAgentService
) -> None:
    await handle_message(message, cmo, cmo_sessions, x_subagent)


async def main() -> None:
    setup_logging()
    settings = get_settings()
    pool = await get_pool()
    await ensure_seed_data(pool, settings)
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    dp.include_router(router)

    async with CMOAgentService(settings, pool) as cmo:
        async with XSubAgentService(settings, pool) as x_subagent:
            dp["cmo"] = cmo
            dp["cmo_sessions"] = SessionStore()
            log.info("bot_starting")
            await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
