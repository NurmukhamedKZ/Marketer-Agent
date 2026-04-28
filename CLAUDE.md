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

**Не вводить:** LangGraph (если только LangChain AgentExecutor не deprecated), Celery, Redis, FastAPI, Docker Compose, vector DB, observability платформы.

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
    cmo_agent.py             # LangChain: стратегия + делегирование
    x_sub_agent.py           # LangChain: написание поста
    prompts.py
    schemas.py
    mcp_client.py            # загрузка MCP tools в LangChain
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

## База данных

Одна миграция: `migrations/001_initial_schema.sql`

**Таблицы:**
- `product_kb` — singleton, знания о продукте (name, one_liner, description, icp, brand_voice, banned_topics, landing_url)
- `signals` — сигналы из Reddit, живут 7 дней, флаг `used`
- `post_ideas` — решения CMO Agent (signal → topic + angle + reasoning), state: `open/consumed/dropped`
- `posts` — посты с state machine

**State machine постов:**
```
draft → pending → approved → published
                └→ rejected        └→ failed → approved (retry)
```

---

## План реализации

### Статус на 2026-04-28

| Шаг | Что | Статус |
|---|---|---|
| 1 | Project skeleton (pyproject.toml, config, structlog, DB pool, migration runner) | ✅ Готово |
| 2 | Schema migration + state_machine.py + тесты | ✅ Готово (частично — state_machine.py есть) |
| 3 | product_kb setup + тест | 🔲 |
| 4 | Reddit collector + signals MCP сервер + тест | 🔲 |
| 5 | posts MCP сервер + utm_builder MCP сервер + тесты | 🔲 |
| 6 | web_search MCP сервер (Tavily wrapper) | 🔲 |
| 7 | Smoke test MCP слоя (скрипт + langchain-mcp-adapters) | 🔲 |
| 8 | X Sub-Agent — вызвать напрямую с ручным post_idea | 🔲 |
| 9 | Telegram bot (aiogram) — send_for_approval + 3 кнопки | 🔲 |
| 10 | X Publisher — привязать к approve callback | 🔲 |
| 11 | CMO Agent — создаёт post_ideas, вызывает X Sub-Agent | 🔲 |
| 12 | Analytics fetcher | 🔲 |
| 13 | Тесты агентов (mocked LLM + MCP) | 🔲 |
| 14 | systemd units, cron, deployment scripts | 🔲 |
| 15 | README | 🔲 |

---

## Правила кодирования

1. **Прочитай весь спек перед тем как писать код.** Не начинай имплементацию сразу.
2. **Проверь LangChain ≥ 1.2 API** перед стартом — `AgentExecutor` мигрировал в LangGraph.
3. **Проверь `langchain-mcp-adapters`** — правильное ли имя пакета, работает ли stdio.
4. **MCP: только stdio транспорт** для MVP. Не поднимать HTTP серверы для MCP.
5. **Не вводить LangGraph** для agent loops, если только `AgentExecutor` не deprecated.
6. **Type hints везде.** `mypy --strict` должен проходить на `app/`.
7. **Все внешние данные через pydantic модели** (LLM outputs, API responses, MCP returns).
8. **Async везде.** Не мешать sync DB calls в async пути.
9. **Одна публичная функция на модуль.** Детали реализации — private.
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