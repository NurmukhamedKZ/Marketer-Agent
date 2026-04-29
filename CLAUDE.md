# Marketer Agent — CLAUDE.md

AI-powered marketing system: два агента (CMO + X Sub-Agent) собирают сигналы из Reddit, генерируют посты для X (Twitter), отправляют на аппрув через Telegram, публикуют и собирают метрики.

---

## Архитектура

```
Reddit API → signals table → CMO Agent → X Sub-Agent → posts table (draft)
                                                              ↓
                                               Telegram Bot (approve/edit/reject)
                                                              ↓ approve
                                                       X Publisher → posts table (published)
                                                              ↓ daily cron
                                                      Analytics Fetcher → posts table (metrics)
```

**Два агента, не один:**
- CMO Agent — стратегия: какой сигнал взять, какой топик/угол, делегирует X Sub-Agent
- X Sub-Agent — тактика: пишет конкретный пост для X

**Инструменты = MCP серверы (FastMCP).** Каждый MCP сервер — отдельный процесс. Агенты подключаются к ним через `langchain-mcp-adapters` (stdio transport).

**product_kb — не MCP сервер.** Это статичный контекст, который читается из БД напрямую через `get_product_kb(pool)` из `app/db/queries.py` и вшивается в system prompt агента перед запуском. MCP нужен только для динамических инструментов, которые агент вызывает сам в процессе reasoning loop.

---

## Стек

| Слой | Выбор |
|---|---|
| Язык | Python 3.12+ |
| Агенты | LangChain ≥ 1.2 (`langchain`, `langchain-anthropic`, `langchain-mcp-adapters`) |
| LLM | Claude Sonnet (`claude-sonnet-4-5`) через `ChatAnthropic` |
| MCP | FastMCP, stdio transport, отдельные процессы |
| Telegram | aiogram v3+ |
| БД | PostgreSQL 18 + asyncpg |
| Reddit | praw |
| X API | tweepy (OAuth 1.0a для постинга, v2 для аналитики) |
| Миграции | Чистый SQL в `migrations/`, свой runner |
| Config | pydantic-settings + `.env` |
| Логи | structlog (JSON в prod) |
| Cron | System cron |
| Supervisor | systemd |
| Пакеты | uv |
| Тесты | pytest + pytest-asyncio |


---

## Структура проекта

```
app/
  config.py                  # pydantic-settings
  db/                        # asyncpg pool + query helpers
  models/                    # pydantic модели + state machine
  signals/
    reddit_collector.py      # PRAW scraper (запускается cron)
  mcp/                       # FastMCP серверы (каждый — отдельный процесс)
    signals_server.py
    posts_server.py
    web_search_server.py
    utm_builder_server.py
  agents/
    cmo_agent_service.py     # CMOAgentService: lifecycle + run() — transport-agnostic
    x_sub_agent_service.py   # XSubAgentService: то же для X sub-agent
    prompts.py               # build_system_prompt(product_kb) — строки промптов
    schemas.py               # pydantic-модели для outputs агентов
  approval/
    bot.py                   # aiogram Dispatcher
    handlers.py              # message + callback handlers
  publisher/
    x_publisher.py           # tweepy
  analytics/
    x_fetcher.py             # daily metrics
```

**Важно для будущего дашборда:** бизнес-логика живёт в `agents/`, `publisher/`, `analytics/` — они никогда не знают про Telegram. `approval/` — изолированный transport слой. Когда придёт время добавить FastAPI, просто добавляем `app/api/` с роутами, которые вызывают те же сервисы.

---

## Агенты — паттерн реализации

Каждый агент реализован как **сервисный класс** с lifecycle через async context manager:

```python
class CMOAgentService:
    def __init__(self, settings: Settings, pool: asyncpg.Pool) -> None: ...

    async def __aenter__(self) -> CMOAgentService:
        # 1. Читает product_kb из БД → строит system_prompt
        # 2. Вызывает MultiServerMCPClient.get_tools() → получает tool definitions
        # 3. Строит агента через create_agent() с InMemorySaver
        ...

    async def __aexit__(self, *args) -> None: ...

    async def run(self, thread_id: str, message: str) -> AsyncIterator[str]:
        # Стримит токены через astream_events(version="v2")
        ...
```

**Правила:**
- `__init__` — только сохраняет зависимости, никакого I/O
- Тяжёлая инициализация (MCP tools, agent build) — только в `__aenter__`
- `run()` — единственный публичный метод; не знает про Telegram или HTTP
- `product_kb` читается один раз при старте, вшивается в system_prompt
- Один инстанс на весь процесс, создаётся в точке входа:

```python
# Telegram bot
async with CMOAgentService(settings, pool) as cmo:
    dp["cmo"] = cmo
    await dp.start_polling()

# FastAPI (future)
async with CMOAgentService(settings, pool) as cmo:
    app.state.cmo = cmo
    yield
```

**Стриминг токенов:**
```python
async for event in agent.astream_events(
    {"messages": [{"role": "user", "content": message}]},
    config={"configurable": {"thread_id": thread_id}, ...},
    version="v2",
):
    if event["event"] == "on_chat_model_stream":
        yield event["data"]["chunk"].content
```

---

## База данных

БД PostgreSQL хостится на **Railway**. Строка подключения в `.env` → `DATABASE_URL`.

Одна миграция: `migrations/001_initial_schema.sql`

**Иерархия:** `users → product_kb (проекты) → signals / post_ideas / posts`

**Таблицы:**
- `users` — пользователи (telegram_id, email)
- `product_kb` — проект пользователя (name, one_liner, description, icp, brand_voice, banned_topics, landing_url); много на одного user
- `signals` — сигналы из Reddit, живут 7 дней, флаг `used`; привязаны к `product_kb_id`
- `post_ideas` — решения CMO Agent (signal → topic + angle + reasoning), state: `open/consumed/dropped`; привязаны к `product_kb_id`
- `posts` — посты с state machine; привязаны к `product_kb_id`

**Для MVP:** создаём одного `user` и один `product_kb` при деплое, везде используем их ID.

**State machine постов:**
```
draft → pending → approved → published
                └→ rejected        └→ failed → approved (retry)
```

---

## План реализации

### Статус на 2026-04-30

| Шаг | Что | Статус |
|---|---|---|
| 1 | Project skeleton (pyproject.toml, config, structlog, DB pool, migration runner) | ✅ Готово |
| 2 | Schema migration + state_machine.py + тесты | ✅ Готово (частично — state_machine.py есть) |
| 3 | product_kb setup + тест | 🔲 |
| 4 | Reddit collector + тесты | ✅ Готово (`app/signals/reddit_collector.py`, 8 тестов) |
| 5 | signals MCP сервер + тест | ✅ Готово |
| 6 | posts MCP сервер + utm_builder MCP сервер + тесты | 🔲 |
| 7 | web_search MCP сервер (Tavily wrapper) | 🔲 |
| 8 | Smoke test MCP слоя (скрипт + langchain-mcp-adapters) | 🔲 |
| 9 | X Sub-Agent — вызвать напрямую с ручным post_idea | 🔲 |
| 10 | Telegram bot (aiogram) — send_for_approval + 3 кнопки | 🔲 |
| 11 | X Publisher — привязать к approve callback | 🔲 |
| 12 | CMO Agent — создаёт post_ideas, вызывает X Sub-Agent | 🔲 |
| 13 | Analytics fetcher | 🔲 |
| 14 | Тесты агентов (mocked LLM + MCP) | 🔲 |
| 15 | systemd units, cron, deployment scripts | 🔲 |
| 16 | README | 🔲 |

---

## Logging

**Файл:** `app/logging_setup.py` — содержит `setup_logging()` и `ToolCallLogger`.

### Инициализация

Вызывать `setup_logging()` **один раз в каждой точке входа**, первым делом до других импортов:
- `app/main.py`
- `app/approval/bot.py`
- каждый MCP-сервер (`app/mcp/*.py`) — они отдельные процессы

```python
from app.logging_setup import setup_logging
setup_logging()
```

### Паттерн в каждом модуле

```python
import time
from uuid import uuid4
import structlog

log = structlog.get_logger()  # на уровне модуля

async def run_cmo_agent(...) -> None:
    run_log = log.bind(component="cmo_agent", run_id=str(uuid4()))
    run_log.info("phase_start", phase="signal_selection")
    t0 = time.monotonic()
    # ... работа ...
    run_log.info("phase_end", phase="signal_selection", duration_ms=round((time.monotonic() - t0) * 1000))
```

### Логирование tool calls (MCP)

Передавать `ToolCallLogger` как LangChain callback — он логирует все tool calls централизованно:

```python
from app.logging_setup import ToolCallLogger

callbacks = [ToolCallLogger("cmo_agent")]
result = await agent.ainvoke({...}, config={"callbacks": callbacks})
```

### Что логировать обязательно

- `phase_start` / `phase_end` с `duration_ms` для каждой фазы агента
- Все tool calls — через `ToolCallLogger` (автоматически)
- State transitions постов: `post_state_transition`, поля `post_id`, `from_state`, `to_state`
- Ошибки с `exc_info=True`

### Конфиг (`.env`)

```
LOG_LEVEL=INFO       # DEBUG / INFO / WARNING / ERROR
LOG_FORMAT=json      # json (prod) | console (dev)
```

---

## LangChain / LangGraph API — важные детали (версии зафиксированы в pyproject.toml)

| Что | Правильно | Неправильно |
|---|---|---|
| Создание агента | `from langchain.agents import create_agent` | `from langgraph.prebuilt import create_react_agent` (deprecated) |
| Параметр промпта | `system_prompt=...` | `prompt=...` (старый API) |
| Тип скомпилированного графа | `from langgraph.pregel import Pregel` | `CompiledGraph` (не существует в 1.1.10) |
| MCP client lifecycle | `client.get_tools()` вызывается один раз при старте | `async with client` — context manager удалён в 0.2.2 |
| MCP сессии | Каждый tool call открывает свою stdio-сессию автоматически | Не нужно держать persistent connection |
| Стриминг | `agent.astream_events(..., version="v2")` | `agent.astream()` даёт chunks, не токены |

---

## Правила кодирования

1. **Прочитай весь спек перед тем как писать код.** Не начинай имплементацию сразу.
2. **Проверь LangChain ≥ 1.2 API** перед стартом — см. таблицу выше.
3. **Проверь `langchain-mcp-adapters`** — правильное ли имя пакета, работает ли stdio.
4. **MCP: только stdio транспорт** для MVP. Не поднимать HTTP серверы для MCP.
5. **Агенты — сервисные классы**, не функции. Один инстанс на процесс, lifecycle через `async with`.
6. **Type hints везде.** `mypy --strict` должен проходить на `app/`.
7. **Все внешние данные через pydantic модели** (LLM outputs, API responses, MCP returns).
8. **Async везде.** Не мешать sync DB calls в async пути.
9. **Один публичный метод на сервис** (`run()`). Детали реализации — `_private`.
10. **Константы из config**, не hardcoded.

---

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.