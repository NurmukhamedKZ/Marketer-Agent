# Agent Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `CMOAgentService` + `XSubAgentService` with a generic `factory.py` + `registry.py` + `AgentRuntime` pattern so adding a new sub-agent is one entry in a list.

**Architecture:** A frozen `SubAgentSpec` dataclass captures per-agent config. `build_agent()` and `as_tool()` in `factory.py` are universal builders. `AgentRuntime` is the single lifecycle class: it builds all sub-agents, wraps them as tools, then builds the CMO agent on top. Each sub-agent gets its own `InMemorySaver` and a fresh `uuid4()` thread per call — fully isolated memory.

**Tech Stack:** LangChain ≥ 1.2 (`create_agent`, `ToolRuntime`), LangGraph (`InMemorySaver`, `Pregel`), `langchain-mcp-adapters`, `langchain-openai`, `asyncpg`, `aiogram v3`, `structlog`.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `app/agents/factory.py` | `SubAgentSpec`, `build_agent()`, `as_tool()`, `_load_web_search()` |
| Create | `app/agents/registry.py` | `SUBAGENTS` list — one `SubAgentSpec` per sub-agent |
| Create | `app/agents/runtime.py` | `AgentRuntime`: lifecycle + `run()` streaming for CMO |
| Modify | `app/agents/context.py` | Remove `signal_id`; keep `product_kb_id` + `post_idea_id` |
| Modify | `app/tools/posts.py` | `create_post_idea`: pass `None` directly instead of `runtime.context.signal_id` |
| Modify | `app/agents/prompts.py` | Remove `build_x_subagent_message` |
| Modify | `app/approval/bot.py` | Use `AgentRuntime` instead of two nested services |
| Modify | `tests/test_x_sub_agent.py` | Rewrite for new `factory.py` API |
| Delete | `app/agents/cmo_agent_service.py` | Replaced by `runtime.py` |
| Delete | `app/agents/x_sub_agent_service.py` | Replaced by `factory.py` + `registry.py` |
| Delete | `app/agents/mcp_client.py` | Replaced by `_load_web_search()` in `factory.py` |

---

## Task 1: Simplify AgentContext — remove signal_id

**Files:**
- Modify: `app/agents/context.py`
- Modify: `app/tools/posts.py`

- [ ] **Step 1: Write a test that AgentContext has no signal_id field**

Add to `tests/test_x_sub_agent.py` (at the top, before existing tests):

```python
def test_agent_context_has_no_signal_id():
    from app.agents.context import AgentContext
    import dataclasses
    fields = {f.name for f in dataclasses.fields(AgentContext)}
    assert "signal_id" not in fields
    assert "product_kb_id" in fields
    assert "post_idea_id" in fields
```

- [ ] **Step 2: Run to verify it fails**

```bash
PYTHONPATH=. pytest tests/test_x_sub_agent.py::test_agent_context_has_no_signal_id -v
```

Expected: `FAILED` — `signal_id` currently exists.

- [ ] **Step 3: Update context.py**

Replace the full content of `app/agents/context.py`:

```python
from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class AgentContext:
    """
    Context injected into every tool call via LangChain ToolRuntime.
    Fields are hidden from the LLM schema — passed at agent invocation time.
    """
    product_kb_id: int
    post_idea_id: UUID | None = field(default=None)
```

- [ ] **Step 4: Update create_post_idea in app/tools/posts.py**

Replace lines 34–49 (the `create_post_idea` tool):

```python
@tool
async def create_post_idea(
    topic: str,
    angle: str,
    cmo_reasoning: str,
    target_platform: platforms,
    runtime: ToolRuntime[AgentContext],
) -> dict:
    """Save the CMO's strategic decision for a signal. Returns post_idea_id."""
    pool = await get_pool()
    return await _insert_post_idea(
        pool,
        runtime.context.product_kb_id,
        None,  # signal_id — not set at CMO level; fetched from post_idea in _insert_post_draft
        topic, angle, cmo_reasoning, target_platform,
    )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
PYTHONPATH=. pytest tests/test_x_sub_agent.py::test_agent_context_has_no_signal_id tests/test_posts_tools.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/agents/context.py app/tools/posts.py tests/test_x_sub_agent.py
git commit -m "refactor: remove signal_id from AgentContext"
```

---

## Task 2: Create factory.py

**Files:**
- Create: `app/agents/factory.py`
- Modify: `tests/test_x_sub_agent.py`

- [ ] **Step 1: Write failing tests for factory.py**

Add to `tests/test_x_sub_agent.py`:

```python
def test_subagent_spec_is_frozen_dataclass():
    import dataclasses
    from app.agents.factory import SubAgentSpec

    spec = SubAgentSpec(name="test", description="desc", system_prompt="prompt", tools=[])
    assert dataclasses.is_dataclass(spec)
    # frozen — mutation raises FrozenInstanceError
    try:
        spec.name = "other"  # type: ignore[misc]
        assert False, "should have raised"
    except dataclasses.FrozenInstanceError:
        pass


def test_as_tool_returns_tool_with_spec_name():
    from unittest.mock import MagicMock, AsyncMock
    from app.agents.factory import SubAgentSpec, as_tool

    spec = SubAgentSpec(name="write_x_post", description="Write an X post.", system_prompt="", tools=[])
    mock_agent = MagicMock()
    tool_fn = as_tool(mock_agent, spec, product_kb_id=1)
    assert tool_fn.name == "write_x_post"


@pytest.mark.asyncio
async def test_as_tool_calls_ainvoke_and_returns_last_message():
    from unittest.mock import MagicMock, AsyncMock
    from langchain_core.messages import AIMessage
    from app.agents.factory import SubAgentSpec, as_tool

    spec = SubAgentSpec(name="write_x_post", description="Write an X post.", system_prompt="", tools=[])

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={
        "messages": [AIMessage(content="ignored"), AIMessage(content="Final post text")]
    })

    tool_fn = as_tool(mock_agent, spec, product_kb_id=42)

    result = await tool_fn.coroutine(
        query="Write a post about SaaS pricing",
        post_idea_id="12345678-1234-5678-1234-567812345678",
    )

    assert result == "Final post text"
    mock_agent.ainvoke.assert_called_once()
    call_args = mock_agent.ainvoke.call_args
    # query is in the message content
    assert "Write a post about SaaS pricing" in call_args[0][0]["messages"][0]["content"]
```

- [ ] **Step 2: Run to verify they fail**

```bash
PYTHONPATH=. pytest tests/test_x_sub_agent.py::test_subagent_spec_is_frozen_dataclass tests/test_x_sub_agent.py::test_as_tool_returns_tool_with_spec_name tests/test_x_sub_agent.py::test_as_tool_calls_ainvoke_and_returns_last_message -v
```

Expected: all FAIL with `ModuleNotFoundError: No module named 'app.agents.factory'`.

- [ ] **Step 3: Create app/agents/factory.py**

```python
from __future__ import annotations

import shlex
from dataclasses import dataclass
from uuid import UUID, uuid4

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.pregel import Pregel

from app.agents.context import AgentContext
from app.config import Settings


@dataclass(frozen=True)
class SubAgentSpec:
    name: str
    description: str
    system_prompt: str
    tools: list[BaseTool]


def build_agent(model, tools: list, system_prompt: str) -> Pregel:
    return create_agent(
        model,
        tools,
        system_prompt=system_prompt,
        context_schema=AgentContext,
        checkpointer=InMemorySaver(),
    )


def as_tool(agent: Pregel, spec: SubAgentSpec, product_kb_id: int) -> BaseTool:
    @tool(spec.name, description=spec.description)
    async def _call(query: str, post_idea_id: str) -> str:
        thread_id = str(uuid4())
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": query}]},
            config={"configurable": {"thread_id": thread_id}},
            context=AgentContext(product_kb_id=product_kb_id, post_idea_id=UUID(post_idea_id)),
        )
        return result["messages"][-1].content

    return _call


async def _load_web_search(settings: Settings) -> list[BaseTool]:
    cmd = settings.mcp_command_for("web_search")
    parts = shlex.split(cmd)
    client = MultiServerMCPClient(
        {"web_search": {"command": parts[0], "args": parts[1:], "transport": "stdio"}}
    )
    return await client.get_tools()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=. pytest tests/test_x_sub_agent.py::test_subagent_spec_is_frozen_dataclass tests/test_x_sub_agent.py::test_as_tool_returns_tool_with_spec_name tests/test_x_sub_agent.py::test_as_tool_calls_ainvoke_and_returns_last_message -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agents/factory.py tests/test_x_sub_agent.py
git commit -m "feat: add SubAgentSpec, build_agent, as_tool factory"
```

---

## Task 3: Create registry.py

**Files:**
- Create: `app/agents/registry.py`

No unit tests needed — it's a pure data file. Correctness is verified when `AgentRuntime` builds successfully in Task 4.

- [ ] **Step 1: Create app/agents/registry.py**

```python
from __future__ import annotations

from app.agents.factory import SubAgentSpec
from app.agents.prompts import build_x_sub_agent_prompt
from app.tools.posts import create_post_draft, list_recent_posts
from app.tools.utm_builder import build_utm_url

SUBAGENTS: list[SubAgentSpec] = [
    SubAgentSpec(
        name="write_x_post",
        description=(
            "Delegate writing a single X (Twitter) post to the X copywriter sub-agent. "
            "Input `query`: a free-form brief with topic, angle, and CMO reasoning. "
            "Input `post_idea_id`: the UUID returned by create_post_idea. "
            "The sub-agent saves the draft and returns a confirmation."
        ),
        system_prompt=build_x_sub_agent_prompt(),
        tools=[build_utm_url, create_post_draft, list_recent_posts],
    ),
]
```

- [ ] **Step 2: Commit**

```bash
git add app/agents/registry.py
git commit -m "feat: add SUBAGENTS registry"
```

---

## Task 4: Create runtime.py

**Files:**
- Create: `app/agents/runtime.py`
- Modify: `tests/test_x_sub_agent.py`

- [ ] **Step 1: Write a failing test for AgentRuntime.run**

Add to `tests/test_x_sub_agent.py`:

```python
@pytest.mark.asyncio
async def test_agent_runtime_run_streams_tokens():
    from unittest.mock import MagicMock, AsyncMock, patch
    from app.agents.runtime import AgentRuntime

    # Build a runtime with a pre-built mock agent (bypass __aenter__)
    runtime = object.__new__(AgentRuntime)
    runtime._kb_id = 1

    async def fake_astream_events(*args, **kwargs):
        for content in ["Hello", " world"]:
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": MagicMock(content=content)},
            }

    mock_agent = MagicMock()
    mock_agent.astream_events = fake_astream_events
    runtime._agent = mock_agent

    tokens = []
    async for token in runtime.run("thread-1", "test message"):
        tokens.append(token)

    assert "".join(tokens) == "Hello world"
```

- [ ] **Step 2: Run to verify it fails**

```bash
PYTHONPATH=. pytest tests/test_x_sub_agent.py::test_agent_runtime_run_streams_tokens -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.agents.runtime'`.

- [ ] **Step 3: Create app/agents/runtime.py**

```python
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg
import structlog
from langchain_openai import ChatOpenAI
from langgraph.pregel import Pregel

from app.agents.context import AgentContext
from app.agents.factory import SubAgentSpec, _load_web_search, as_tool, build_agent
from app.agents.prompts import build_system_prompt
from app.agents.registry import SUBAGENTS
from app.config import Settings
from app.db.queries import get_product_kb
from app.logging_setup import ToolCallLogger
from app.tools.posts import create_post_idea, list_recent_posts

log = structlog.get_logger()


class AgentRuntime:
    def __init__(self, settings: Settings, pool: asyncpg.Pool) -> None:
        self._settings = settings
        self._pool = pool
        self._agent: Pregel | None = None
        self._kb_id: int | None = None

    async def __aenter__(self) -> AgentRuntime:
        kb = await get_product_kb(self._pool)
        self._kb_id = kb.id

        model = ChatOpenAI(
            model=self._settings.openai_model,
            api_key=self._settings.openai_api_key,
            temperature=self._settings.llm_temperature,
            max_tokens=self._settings.llm_max_tokens,
        )
        web_search = await _load_web_search(self._settings)

        subagent_tools = [
            as_tool(
                build_agent(model, [*spec.tools, *web_search], spec.system_prompt),
                spec,
                kb.id,
            )
            for spec in SUBAGENTS
        ]

        self._agent = build_agent(
            model,
            [create_post_idea, list_recent_posts, *web_search, *subagent_tools],
            build_system_prompt(kb),
        )
        log.info("agent_runtime_started", subagents=[s.name for s in SUBAGENTS])
        return self

    async def __aexit__(self, *args: object) -> None:
        self._agent = None
        log.info("agent_runtime_stopped")

    async def run(self, thread_id: str, message: str) -> AsyncIterator[str]:
        assert self._agent is not None, "Call __aenter__ before run()"
        run_log = log.bind(component="cmo_agent", run_id=str(uuid4()), thread_id=thread_id)
        run_log.info("run_start")
        t0 = time.monotonic()

        async for event in self._agent.astream_events(
            {"messages": [{"role": "user", "content": message}]},
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": 100,
                "callbacks": [ToolCallLogger("cmo_agent")],
            },
            context=AgentContext(product_kb_id=self._kb_id),
            version="v2",
        ):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    yield chunk.content

        run_log.info("run_end", duration_ms=round((time.monotonic() - t0) * 1000))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=. pytest tests/test_x_sub_agent.py::test_agent_runtime_run_streams_tokens -v
```

Expected: PASS.

- [ ] **Step 5: Run all x_sub_agent tests**

```bash
PYTHONPATH=. pytest tests/test_x_sub_agent.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/agents/runtime.py tests/test_x_sub_agent.py
git commit -m "feat: add AgentRuntime — single lifecycle class for CMO + sub-agents"
```

---

## Task 5: Update bot.py to use AgentRuntime

**Files:**
- Modify: `app/approval/bot.py`

- [ ] **Step 1: Replace bot.py content**

```python
from __future__ import annotations

import asyncio

import structlog
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.agents.runtime import AgentRuntime
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
    cmo: AgentRuntime,
    cmo_sessions: SessionStore,
) -> None:
    await handle_message(message, cmo, cmo_sessions)


async def main() -> None:
    setup_logging()
    settings = get_settings()
    pool = await get_pool()
    await ensure_seed_data(pool, settings)
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    dp.include_router(router)

    async with AgentRuntime(settings, pool) as cmo:
        dp["cmo"] = cmo
        dp["cmo_sessions"] = SessionStore()
        log.info("bot_starting")
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify handlers.py type annotation still works**

Open `app/approval/handlers.py`. The `cmo` parameter is typed as `CMOAgentService`. Update the import and type hint:

```python
from __future__ import annotations

import structlog
from aiogram.types import Message

from app.agents.runtime import AgentRuntime
from app.approval.session_store import SessionStore

log = structlog.get_logger()


async def cmd_new(message: Message, cmo_sessions: SessionStore) -> None:
    """Create a fresh conversation thread for this chat."""
    thread_id = cmo_sessions.new_session(message.chat.id)
    log.info("new_session_created", chat_id=message.chat.id, thread_id=thread_id)
    await message.reply("Новая сессия начата. Можешь писать!")


async def handle_message(
    message: Message,
    cmo: AgentRuntime,
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
```

- [ ] **Step 3: Run telegram bot tests**

```bash
PYTHONPATH=. pytest tests/test_telegram_bot.py -v
```

Expected: all PASS (tests mock `cmo.run`, interface unchanged).

- [ ] **Step 4: Commit**

```bash
git add app/approval/bot.py app/approval/handlers.py
git commit -m "refactor: wire AgentRuntime into bot.py"
```

---

## Task 6: Clean up prompts.py and rewrite prompt-related tests

**Files:**
- Modify: `app/agents/prompts.py`
- Modify: `tests/test_x_sub_agent.py`

- [ ] **Step 1: Remove build_x_subagent_message from prompts.py**

Remove the `build_x_subagent_message` function (lines 77–90). Final `prompts.py`:

```python
from app.models.product_kb import ProductKB

_CMO_SYSTEM_PROMPT = """You are a senior content marketer.

## What you do
1. Research 3–5 trending topics relevant to the product and audience
2. Pick the strongest angle — timely, relevant, not already covered
3. Draft a post that stops the scroll in the first line
4. Present the draft to the user and ask for feedback or approval

## Writing rules
- Lead with tension, a question, or a surprising insight — never with the brand name
- One idea per post. Cut everything that doesn't serve it.
- Match the brand voice exactly as described by the user
- No hashtag spam. One max, only if it earns its place.
- Never invent statistics or quotes

## Your mindset
You think like a founder who also happens to write well. You have opinions. If you think a topic is weak, say so and suggest a better one. You're here to drive results, not to produce content for its own sake."""

_PRODUCT_KB_SECTION = """
## Product context
Name: {name}
What it does: {one_liner}
ICP: {icp}
Brand voice: {brand_voice}
Landing URL: {landing_url}
Banned topics: {banned_topics}"""


def build_system_prompt(product_kb: ProductKB | None = None) -> str:
    if product_kb is None:
        return _CMO_SYSTEM_PROMPT
    section = _PRODUCT_KB_SECTION.format(
        name=product_kb.product_name,
        one_liner=product_kb.one_liner,
        icp=product_kb.icp,
        brand_voice=product_kb.brand_voice,
        landing_url=product_kb.landing_url,
        banned_topics=", ".join(product_kb.banned_topics) if product_kb.banned_topics else "none",
    )
    return _CMO_SYSTEM_PROMPT + section


_X_SUB_AGENT_SYSTEM_PROMPT = """You are an expert X (Twitter) copywriter.

## Your job
Write a single X post based on the strategic brief from the CMO.

## Rules
- Max 270 characters
- Lead with tension, a question, or a surprising insight — never with the brand name
- One idea per post. Cut everything that doesn't serve it.
- Use build_utm_url to create a tracking link before saving the draft
- Use list_recent_posts to check for duplicates before finalising
- Save the result with create_post_draft — that is your final action

## When done
Call create_post_draft with your draft text, your reasoning, and the UTM url.
Do not output anything after."""


def build_x_sub_agent_prompt(product_kb: ProductKB | None = None) -> str:
    if product_kb is None:
        return _X_SUB_AGENT_SYSTEM_PROMPT
    section = _PRODUCT_KB_SECTION.format(
        name=product_kb.product_name,
        one_liner=product_kb.one_liner,
        icp=product_kb.icp,
        brand_voice=product_kb.brand_voice,
        landing_url=product_kb.landing_url,
        banned_topics=", ".join(product_kb.banned_topics) if product_kb.banned_topics else "none",
    )
    return _X_SUB_AGENT_SYSTEM_PROMPT + section
```

- [ ] **Step 2: Remove deleted-code tests from test_x_sub_agent.py**

Remove these two test functions that test the now-deleted `build_x_subagent_message` and `make_invoke_x_sub_agent_tool`:
- `test_build_x_subagent_message_no_retry`
- `test_build_x_subagent_message_with_retry_includes_context`
- `test_make_invoke_x_sub_agent_tool_returns_tool_with_correct_name`
- `test_make_invoke_x_sub_agent_tool_calls_service_run`

Also remove the now-unused import at top of file:
```python
from app.agents.prompts import build_x_sub_agent_prompt, build_x_subagent_message
```
Replace with:
```python
from app.agents.prompts import build_x_sub_agent_prompt
```

- [ ] **Step 3: Run all x_sub_agent tests to verify nothing broke**

```bash
PYTHONPATH=. pytest tests/test_x_sub_agent.py -v
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add app/agents/prompts.py tests/test_x_sub_agent.py
git commit -m "refactor: remove build_x_subagent_message, clean up test_x_sub_agent"
```

---

## Task 7: Delete old files and run full suite

**Files:**
- Delete: `app/agents/cmo_agent_service.py`
- Delete: `app/agents/x_sub_agent_service.py`
- Delete: `app/agents/mcp_client.py`

- [ ] **Step 1: Delete the three old files**

```bash
rm app/agents/cmo_agent_service.py app/agents/x_sub_agent_service.py app/agents/mcp_client.py
```

- [ ] **Step 2: Grep for any remaining imports of deleted modules**

```bash
grep -r "cmo_agent_service\|x_sub_agent_service\|mcp_client" app/ tests/ --include="*.py"
```

Expected: no output. If any references appear, fix them.

- [ ] **Step 3: Run the full test suite**

```bash
PYTHONPATH=. pytest tests/ -v --ignore=tests/test_mcp_web_search.py --ignore=tests/test_mcp_client.py
```

(MCP integration tests are excluded — they require a live MCP server.)

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add -u
git commit -m "refactor: delete CMOAgentService, XSubAgentService, mcp_client — replaced by factory + registry + AgentRuntime"
```
