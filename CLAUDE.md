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

**Инструменты — два типа:**
- **`@tool` функции** (`app/tools/`) — для DB операций (posts, post_ideas) и stateless утилит (utm_builder). Живут в том же процессе что и агент. Контекст (`product_kb_id`, `post_idea_id`) инжектируется через `ToolRuntime[AgentContext]` — LLM эти поля не видит.
- **MCP серверы** (`app/mcp/`) — только для внешних API. Сейчас: `web_search` (Tavily). Отдельные процессы, stdio transport, `langchain-mcp-adapters`.

**product_kb — не инструмент.** Статичный контекст, читается из БД через `get_product_kb(pool)` из `app/db/queries.py` и вшивается в system prompt агента перед запуском.

---

## ВАЖНО, пользовательские правила:
1) Перед тем как писать какой либо код на LangChain или LangGraph, ты должен прочитать актуальную документацию через context7 MCP
2) Не меней версий пакетов и зависимостей
3) Не делай комиты в гит

---

## Стек

| Слой | Выбор |
|---|---|
| Язык | Python 3.12+ |
| Агенты | LangChain ≥ 1.2 (`langchain`, `langchain-openai`, `langchain-mcp-adapters`) |
| LLM | GPT (`gpt-5.4-mini`) через `ChatOpenAI` |
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
  mcp/                       # FastMCP серверы — только для внешних API
    web_search.py            # Tavily wrapper (отдельный процесс, stdio) + web_search_session() клиентский контекст-менеджер
  tools/                     # LangChain @tool функции (in-process)
    posts.py                 # create_post_idea, create_post_draft, list_recent_posts, get_post
    utm_builder.py           # build_utm_url (stateless)
  agents/
    context.py               # AgentContext dataclass (product_kb_id, post_idea_id)
    factory.py               # SubAgentSpec, build_agent(), as_tool(), _load_web_search()
    registry.py              # SUBAGENTS list — одна запись = один sub-agent
    runtime.py               # AgentRuntime: lifecycle + run() — transport-agnostic
    prompts.py               # build_system_prompt, build_x_sub_agent_prompt
  approval/
    bot.py                   # aiogram Dispatcher + точка входа (python -m app.approval.bot)
    handlers.py              # cmd_new, handle_message — transport-agnostic, без aiogram internals
    session_store.py         # SessionStore: {chat_id → thread_id} in-memory
  publisher/
    x_publisher.py           # tweepy
  analytics/
    x_fetcher.py             # daily metrics
scripts/
  test_x_subagent.py        # smoke test: вызов X Sub-Agent напрямую (PYTHONPATH=. python scripts/test_x_subagent.py <post_idea_id>)
```

**Важно для будущего дашборда:** бизнес-логика живёт в `agents/`, `publisher/`, `analytics/` — они никогда не знают про Telegram. `approval/` — изолированный transport слой. Когда придёт время добавить FastAPI, просто добавляем `app/api/` с роутами, которые вызывают те же сервисы.

---

## Агенты — паттерн реализации

Все агенты строятся через **factory + registry**. Один класс `AgentRuntime` управляет lifecycle CMO и всех sub-агентов.

### factory.py — универсальные строители

```python
@dataclass(frozen=True)
class SubAgentSpec:
    name: str           # имя tool, которое видит CMO LLM
    description: str
    system_prompt: str
    tools: list[BaseTool]

def build_agent(model: BaseChatModel, tools: list, system_prompt: str) -> Pregel:
    return create_agent(model, tools, system_prompt=system_prompt,
                        context_schema=AgentContext, checkpointer=InMemorySaver())

def as_tool(agent: Pregel, spec: SubAgentSpec, product_kb_id: int) -> BaseTool:
    @tool(spec.name, description=spec.description)
    async def _call(query: str, post_idea_id: str) -> str:
        thread_id = str(uuid4())   # свежий thread → изолированная память
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": query}]},
            config={"configurable": {"thread_id": thread_id}},
            context=AgentContext(product_kb_id=product_kb_id, post_idea_id=UUID(post_idea_id)),
        )
        return result["messages"][-1].content
    return _call
```

### registry.py — добавить sub-агента = одна запись

```python
SUBAGENTS: list[SubAgentSpec] = [
    SubAgentSpec(
        name="write_x_post",
        description="...",
        system_prompt=build_x_sub_agent_prompt(),
        tools=[build_utm_url, create_post_draft, list_recent_posts],
    ),
    # + LinkedIn, Email, etc. — одна запись
]
```

### AgentRuntime — единственный lifecycle класс

```python
class AgentRuntime:
    def __init__(self, settings: Settings, pool: asyncpg.Pool) -> None:
        self._exit_stack = AsyncExitStack()  # держит MCP сессию живой
        ...

    async def __aenter__(self) -> AgentRuntime:
        kb = await get_product_kb(pool)
        model = ChatOpenAI(...)
        # Открываем persistent stdio-сессию — subprocess живёт весь lifetime runtime
        _, web_search = await self._exit_stack.enter_async_context(
            web_search_session()   # из app/mcp/web_search.py
        )
        subagent_tools = [
            as_tool(build_agent(model, [*spec.tools, *web_search], spec.system_prompt), spec, kb.id)
            for spec in SUBAGENTS
        ]
        self._agent = build_agent(model,
            [create_post_idea, list_recent_posts, *web_search, *subagent_tools],
            build_system_prompt(kb))
        ...

    async def __aexit__(self, *args) -> None:
        await self._exit_stack.aclose()  # закрывает MCP subprocess
        ...

    async def run(self, thread_id: str, message: str) -> AsyncIterator[str]:
        # Стримит токены через astream_events(version="v2")
        ...
```

**Правила:**
- `__init__` — только сохраняет зависимости, никакого I/O
- Тяжёлая инициализация (MCP tools, agent build) — только в `__aenter__`
- `run()` — единственный публичный метод; не знает про Telegram или HTTP
- `product_kb` читается один раз при старте, вшивается в system_prompt
- Один инстанс на весь процесс:

```python
# Telegram bot
async with AgentRuntime(settings, pool) as cmo:
    dp["cmo"] = cmo
    dp["cmo_sessions"] = SessionStore()
    await dp.start_polling(bot)

# FastAPI (future)
async with AgentRuntime(settings, pool) as cmo:
    app.state.cmo = cmo
    yield
```

**Важно:** перед стартом обязательно вызвать `ensure_seed_data(pool, settings)` — иначе `get_product_kb()` вернёт `None` и `__aenter__` упадёт с `AttributeError`.

### Изоляция памяти sub-агентов

| Граница | Механизм |
|---|---|
| Между sub-агентами | Отдельные `Pregel` инстансы → отдельные `InMemorySaver` |
| Между вызовами одного sub-агента | Свежий `uuid4()` thread_id на каждый `as_tool()` вызов |
| Sub-агент vs CMO | CMO видит только `messages[-1].content`, не внутренние сообщения |

**Стриминг токенов (CMO):**
```python
async for event in self._agent.astream_events(
    {"messages": [{"role": "user", "content": message}]},
    config={"configurable": {"thread_id": thread_id},
            "recursion_limit": 100, "callbacks": [ToolCallLogger("cmo_agent")]},
    context=AgentContext(product_kb_id=self._kb_id),
    version="v2",
):
    if event["event"] == "on_chat_model_stream":
        if chunk := event["data"]["chunk"].content:
            yield chunk
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
| 3 | product_kb setup + тест | ✅ Готово |
| 4 | Reddit collector + тесты | ✅ Готово (`app/signals/reddit_collector.py`, 8 тестов) |
| 5 | signals MCP сервер + тест | ✅ Готово |
| 6 | posts @tool функции + utm_builder + AgentContext + mcp_client + тесты | ✅ Готово (`app/tools/`, `app/agents/context.py`, `app/agents/mcp_client.py`) |
| 7 | web_search MCP сервер (Searxng) | ✅ Готово |
| 8 | Smoke test MCP слоя (скрипт + langchain-mcp-adapters) | ✅ Готово (`tests/test_mcp_web_search.py` — 23 теста, `tests/test_mcp_client.py` — 6 smoke тестов) |
| 9 | X Sub-Agent — вызвать напрямую с ручным post_idea | ✅ Готово (`scripts/test_x_subagent.py`, 9 тестов) |
| 9b | Рефакторинг агентов: factory + registry + AgentRuntime | ✅ Готово (`app/agents/factory.py`, `registry.py`, `runtime.py`, 26 тестов) |
| 10 | Telegram bot (aiogram) — основа: `/new` команда + conversation с CMO Agent | ✅ Готово (`app/approval/bot.py`, `handlers.py`, `session_store.py`, 9 тестов) |
| 10b | Telegram bot — send_for_approval + 3 кнопки (approve/edit/reject) | 🔲 |
| 11 | X Publisher — привязать к approve callback | 🔲 |
| 12 | CMO Agent — создаёт post_ideas, вызывает X Sub-Agent | 🔲 |
| 13 | Analytics fetcher | 🔲 |
| 14 | Тесты агентов (mocked LLM + MCP) | 🔲 |
| 15 | systemd units, cron, deployment scripts | 🔲 |
| 16 | README | 🔲 |

---

## @tool + ToolRuntime — паттерн реализации

Все DB-инструменты агентов живут в `app/tools/`. Паттерн: приватный хелпер для логики + публичный `@tool` для LangChain.

```python
from langchain.tools import tool, ToolRuntime  # НЕ langchain_core.tools — ToolRuntime там не экспортируется
from app.agents.context import AgentContext
from app.db import get_pool

# Приватный хелпер — тестируется напрямую, без ToolRuntime
# signal_id не передаётся — он хранится в post_ideas и читается в _insert_post_draft через JOIN
async def _insert_post_idea(pool, product_kb_id, topic, angle, reasoning, platform) -> dict:
    row = await pool.fetchrow("""
        INSERT INTO post_ideas (product_kb_id, signal_id, topic, angle, cmo_reasoning, target_platform)
        VALUES ($1, NULL, $2, $3, $4, $5) RETURNING id
    """, product_kb_id, topic, angle, reasoning, platform)
    return {"post_idea_id": str(row["id"])}

# Публичный @tool — только прокси, контекст из ToolRuntime
@tool
async def create_post_idea(
    topic: str,
    angle: str,
    cmo_reasoning: str,
    target_platform: str,
    runtime: ToolRuntime[AgentContext],  # LLM это поле НЕ видит
) -> dict:
    """Save the CMO's strategic decision for a signal. Returns post_idea_id."""
    pool = await get_pool()
    return await _insert_post_idea(
        pool,
        runtime.context.product_kb_id,  # из AgentContext, не от LLM
        topic, angle, cmo_reasoning, target_platform,
    )
```

**`AgentContext` — только два поля:**
```python
@dataclass
class AgentContext:
    product_kb_id: int
    post_idea_id: UUID | None = None  # заполняется только для sub-агентов
```
`signal_id` убран — он никогда не передавался на уровне CMO, а `_insert_post_draft` читает его из `post_ideas` через DB.

**Как работает ToolRuntime:**
1. `create_agent(model, tools, context_schema=AgentContext)` — регистрирует схему контекста
2. `agent.astream_events(..., context=AgentContext(product_kb_id=...))` — передаёт контекст
3. LangChain автоматически заполняет `runtime.context` из этого контекста при каждом вызове инструмента
4. `runtime: ToolRuntime[AgentContext]` убирается из LLM-видимой схемы автоматически

**Проверка схемы:**
```python
# Правильно — смотреть через model.bind_tools
bound = model.bind_tools([create_post_idea])
# Видно: ['topic', 'angle', 'cmo_reasoning', 'target_platform'] — без runtime ✅

# Неправильно — падает с PydanticInvalidForJsonSchema
create_post_idea.args_schema.model_json_schema()  # ❌ не использовать
```

**Тестирование — вызывать приватный хелпер напрямую:**
```python
async def test_create_post_idea(db_pool, seed_ids):
    result = await _insert_post_idea(
        db_pool, seed_ids["product_kb_id"],
        "topic", "angle", "reasoning", "x",
    )
    assert "post_idea_id" in result
```

---

## Telegram Bot — паттерн реализации

**`app/approval/session_store.py`** — изолированный класс без зависимостей на aiogram:
```python
class SessionStore:
    def get_or_create(self, chat_id: int) -> str: ...  # возвращает текущую или создаёт новую
    def new_session(self, chat_id: int) -> str: ...    # всегда создаёт новую (для /new)
```

**`app/approval/handlers.py`** — хендлеры без aiogram internals, тестируемы через MagicMock:
```python
async def cmd_new(message: Message, cmo_sessions: SessionStore) -> None: ...
async def handle_message(message: Message, cmo: AgentRuntime, cmo_sessions: SessionStore) -> None: ...
```

**`app/approval/bot.py`** — DI через `dp[...]`, aiogram v3 паттерн:
```python
dp["cmo"] = cmo
dp["cmo_sessions"] = SessionStore()
# aiogram автоматически инжектирует их в хендлеры по имени параметра
```

**Тестирование хендлеров** — `AsyncMock` для `message`, обычный `MagicMock` для сервисов:
```python
message = AsyncMock()
message.chat.id = 42
cmo.run = fake_run  # async generator
await handle_message(message, cmo, store)
message.answer.assert_called_once_with("Hello world")
```

---

## Sub-Agent — паттерн реализации

Sub-агент оборачивается в `@tool` через `as_tool()` из `factory.py`. CMO LLM вызывает его как обычный инструмент.

**Интерфейс tool для CMO:**
```python
# as_tool() создаёт tool с двумя аргументами:
# - query: str — свободный бриф (тема, угол, reasoning — CMO LLM формулирует сам)
# - post_idea_id: str — UUID из create_post_idea, нужен для create_post_draft
```

**Ключевые свойства:**
- Sub-agent вызывается через `agent.ainvoke()` (не стрим) — CMO ждёт полного результата
- Свежий `uuid4()` thread_id на каждый вызов — чистая история, без загрязнения
- Каждый sub-agent имеет свой `InMemorySaver` — изолированная память
- Параллельные вызовы безопасны: checkpointer ключуется по `thread_id`

**Тестирование `as_tool`:**
```python
# Для async @tool — вызывать через .coroutine, НЕ .func (.func is None для async)
result = await tool_fn.coroutine(
    query="Write a post about SaaS pricing",
    post_idea_id="12345678-1234-5678-1234-567812345678",
)
# Проверять context= в ainvoke call:
assert call_args.kwargs["context"].product_kb_id == 42
```

**post_idea_id через `AgentContext`:**
CMO LLM создаёт post_idea → получает `{"post_idea_id": "abc-123"}` → передаёт его в `as_tool`-обёртку → `as_tool` кладёт в `AgentContext(post_idea_id=UUID(...))` → sub-agent читает через `runtime.context.post_idea_id` в `create_post_draft`.

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
| MCP client lifecycle | `async with client.session("web_search") as session` + `load_mcp_tools(session)` — persistent subprocess | `async with MultiServerMCPClient(...)` — context manager удалён в 0.1.0, `NotImplementedError` |
| MCP сессии | `load_mcp_tools(session=session)` — все tool calls используют одну сессию, subprocess не пересоздаётся | `load_mcp_tools(session=None, connection=...)` — новый subprocess на каждый вызов инструмента |
| Persistent MCP в AgentRuntime | `AsyncExitStack` + `web_search_session()` из `app/mcp/web_search.py` открывается в `__aenter__`, закрывается в `__aexit__` | Держать клиент без сессии — subprocess всё равно пересоздаётся per call |
| Стриминг | `agent.astream_events(..., version="v2")` | `agent.astream()` даёт chunks, не токены |
| Скрытый контекст в @tool | `runtime: ToolRuntime[AgentContext]` в сигнатуре + `context_schema=AgentContext` в `create_agent` | ContextVar (не нужен — ToolRuntime работает нативно) |
| Передача контекста при вызове | `agent.astream_events(..., context=AgentContext(...))` | Передавать через аргументы инструмента (LLM увидит) |
| Проверка LLM-видимой схемы | `model.bind_tools([tool])` и смотреть на tool_calls в ответе | `tool.args_schema.model_json_schema()` — падает с PydanticInvalidForJsonSchema для ToolRuntime |
| `args_schema` MCP инструментов (из `langchain-mcp-adapters`) | `tool.args_schema` — это plain `dict` (JSON Schema); доступ: `tool.args_schema.get("properties", {})` | `tool.args_schema.model_json_schema()` — AttributeError, т.к. это не Pydantic-модель |
| FastMCP `@mcp.tool` | Декоратор оставляет функцию callable: `await web_search(query, count)` — работает напрямую | — |
| Запуск MCP сервера web_search | `python -m app.mcp.web_search` | `python -m app.mcp.web_search_server` — модуль не существует |
| Импорт `ToolRuntime` | `from langchain.tools import tool, ToolRuntime` | `from langchain_core.tools import ToolRuntime` — не экспортируется, `ImportError` |
| Тест async `@tool` напрямую | `await tool_fn.coroutine(arg1=..., arg2=...)` | `tool_fn.func(...)` — `func` is `None` для async tools, `TypeError` |
| `ToolCallLogger.on_tool_end` — тип `output` | `output.content if hasattr(output, "content") else str(output)` | `output[:200]` — `ToolMessage` не subscriptable в новых версиях LangChain |
| Загрузка MCP tools | `from app.mcp.web_search import web_search_session` — единственная точка | `from app.mcp.all_mcp import ...` — файл удалён |
| MCP серверы для агентов | только `"web_search"` через `web_search_session()` | `"signals"`, `"posts"` — этих MCP серверов не существует, это `@tool` функции в `app/tools/` |


---

## Правила кодирования

1. **Прочитай весь спек перед тем как писать код.** Не начинай имплементацию сразу.
2. **Проверь LangChain ≥ 1.2 API** перед стартом — см. таблицу выше.
3. **Проверь `langchain-mcp-adapters`** — правильное ли имя пакета, работает ли stdio.
4. **Инструменты — `@tool`, не MCP по умолчанию.** MCP только когда нужна изоляция процесса (внешние API). DB-операции и stateless утилиты → `@tool` в `app/tools/`.
5. **MCP: только stdio транспорт** для MVP. Не поднимать HTTP серверы для MCP.
6. **Агенты — сервисные классы**, не функции. Один инстанс на процесс, lifecycle через `async with`.
7. **Type hints везде.** `mypy --strict` должен проходить на `app/`.
8. **Все внешние данные через pydantic модели** (LLM outputs, API responses, MCP returns).
9. **Async везде.** Не мешать sync DB calls в async пути.
10. **Один публичный метод на сервис** (`run()`). Детали реализации — `_private`.
11. **Константы из config**, не hardcoded.

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