# Telegram Bot (aiogram v3)

File: `approval/bot.py`

```python
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from mktg_agent.config import get_settings
from mktg_agent.db import get_pool
from mktg_agent.state_machine import transition_post
from mktg_agent.publisher.x_publisher import publish_post
import structlog

log = structlog.get_logger()
settings = get_settings()

bot = Bot(token=settings.telegram_bot_token)
dp = Dispatcher(storage=MemoryStorage())

class EditFlow(StatesGroup):
    awaiting_edit = State()

class RejectFlow(StatesGroup):
    awaiting_reason = State()

def build_approval_keyboard(post_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Approve", callback_data=f"approve:{post_id}"),
        InlineKeyboardButton(text="❌ Reject",  callback_data=f"reject:{post_id}"),
        InlineKeyboardButton(text="✏️ Edit",    callback_data=f"edit:{post_id}"),
    ]])

async def send_for_approval(post_id: str) -> int:
    """Called by the X Sub-Agent. Returns Telegram message_id."""
    pool = await get_pool()
    post = await pool.fetchrow("""
        SELECT p.*, s.title AS signal_title, s.subreddit, s.url AS signal_url
        FROM posts p
        LEFT JOIN signals s ON s.id = p.signal_id
        WHERE p.id = $1
    """, post_id)
    
    text = format_approval_message(post)
    msg = await bot.send_message(
        chat_id=settings.telegram_owner_chat_id,
        text=text,
        reply_markup=build_approval_keyboard(post_id),
        disable_web_page_preview=True,
    )
    return msg.message_id

# Owner-only middleware
@dp.message.middleware()
@dp.callback_query.middleware()
async def owner_only(handler, event, data):
    chat_id = (event.from_user.id if hasattr(event, "from_user") else None)
    if chat_id != settings.telegram_owner_chat_id:
        log.warning("unauthorized_telegram_user", chat_id=chat_id)
        return
    return await handler(event, data)

@dp.callback_query(F.data.startswith("approve:"))
async def on_approve(cb: CallbackQuery):
    post_id = cb.data.split(":", 1)[1]
    await transition_post(post_id, from_state="pending", to_state="approved")
    await cb.message.edit_text(cb.message.text + "\n\n✅ Approved")
    await cb.answer("Publishing…")
    asyncio.create_task(publish_post(post_id))

@dp.callback_query(F.data.startswith("reject:"))
async def on_reject(cb: CallbackQuery, state: FSMContext):
    post_id = cb.data.split(":", 1)[1]
    await state.update_data(post_id=post_id)
    await state.set_state(RejectFlow.awaiting_reason)
    await cb.message.reply("Reason for rejection? (or /skip)")
    await cb.answer()

@dp.message(RejectFlow.awaiting_reason)
async def on_rejection_reason(msg: Message, state: FSMContext):
    data = await state.get_data()
    post_id = data["post_id"]
    reason = "" if msg.text == "/skip" else msg.text
    await transition_post(
        post_id, from_state="pending", to_state="rejected",
        rejection_reason=reason,
    )
    await msg.reply("❌ Rejected.")
    await state.clear()

@dp.callback_query(F.data.startswith("edit:"))
async def on_edit_start(cb: CallbackQuery, state: FSMContext):
    post_id = cb.data.split(":", 1)[1]
    await state.update_data(post_id=post_id, original_message_id=cb.message.message_id)
    await state.set_state(EditFlow.awaiting_edit)
    await cb.message.reply("Reply with the edited post text.")
    await cb.answer()

@dp.message(EditFlow.awaiting_edit)
async def on_edit_submitted(msg: Message, state: FSMContext):
    data = await state.get_data()
    post_id = data["post_id"]
    new_text = msg.text
    
    if len(new_text) > settings.post_max_chars:
        await msg.reply(f"Too long ({len(new_text)} chars). Try again.")
        return
    
    pool = await get_pool()
    await pool.execute(
        "UPDATE posts SET final_text = $1 WHERE id = $2",
        new_text, post_id,
    )
    # Re-render the approval message with the new text and buttons
    post = await pool.fetchrow("""
        SELECT p.*, s.title AS signal_title, s.subreddit, s.url AS signal_url
        FROM posts p LEFT JOIN signals s ON s.id = p.signal_id
        WHERE p.id = $1
    """, post_id)
    await bot.edit_message_text(
        chat_id=msg.chat.id,
        message_id=data["original_message_id"],
        text=format_approval_message(post, edited=True),
        reply_markup=build_approval_keyboard(post_id),
        disable_web_page_preview=True,
    )
    await state.clear()
    await msg.reply("✏️ Edit saved. Approve or reject in the original message.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
```

`format_approval_message(post, edited=False)` is a helper that produces the message body shown to the user, including signal context, draft text, char count, and reasoning.
