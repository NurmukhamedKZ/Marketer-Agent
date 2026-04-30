# X Sub-Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `XSubAgentService` — a focused LangChain agent that writes X (Twitter) posts from a CMO strategic brief — callable directly via test script and as a `@tool` by CMO Agent.

**Architecture:** `XSubAgentService` mirrors `CMOAgentService`'s lifecycle pattern (async context manager, one instance per process). It uses `web_search` MCP + three in-process `@tool` functions. A `make_invoke_x_sub_agent_tool(service)` factory returns the `@tool` CMO will call in step 12. Step 9 goal is verified by a direct `run()` call from `scripts/test_x_subagent.py`.

**Tech Stack:** LangChain ≥ 1.2 (`langchain.agents.create_agent`), `langchain-anthropic`, `langchain-mcp-adapters`, `langgraph` (`InMemorySaver`, `Pregel`), `asyncpg`, `structlog`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `app/agents/prompts.py` | Add `_X_SUB_AGENT_SYSTEM_PROMPT`, `build_x_sub_agent_prompt()`, `build_x_subagent_message()` |
| Create | `app/agents/x_sub_agent_service.py` | `XSubAgentService` class + `make_invoke_x_sub_agent_tool()` factory |
| Create | `tests/test_x_sub_agent.py` | Unit tests for prompt functions and tool factory |
| Create | `scripts/test_x_subagent.py` | Smoke test — direct invocation with manual post_idea |

---

### Task 1: Add X Sub-Agent prompt functions to `prompts.py`

**Files:**
- Modify: `app/agents/prompts.py`
- Test: `tests/test_x_sub_agent.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_x_sub_agent.py`:

```python
from datetime import datetime

import pytest

from app.agents.prompts import build_x_sub_agent_prompt, build_x_subagent_message
from app.models.product_kb import ProductKB


def _make_kb(**overrides) -> ProductKB:
    defaults = dict(
        id=1,
        user_id=1,
        product_name="TestProduct",
        one_liner="A test product",
        description="desc",
        icp="developers",
        brand_voice="friendly",
        banned_topics=["politics"],
        landing_url="https://example.com",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    defaults.update(overrides)
    return ProductKB(**defaults)


def test_build_x_sub_agent_prompt_no_kb_contains_role():
    prompt = build_x_sub_agent_prompt(None)
    assert "X (Twitter) copywriter" in prompt


def test_build_x_sub_agent_prompt_no_kb_contains_tool_instructions():
    prompt = build_x_sub_agent_prompt(None)
    assert "create_post_draft" in prompt
    assert "build_utm_url" in prompt
    assert "list_recent_posts" in prompt


def test_build_x_sub_agent_prompt_with_kb_contains_product_name():
    prompt = build_x_sub_agent_prompt(_make_kb())
    assert "TestProduct" in prompt


def test_build_x_sub_agent_prompt_with_kb_contains_icp():
    prompt = build_x_sub_agent_prompt(_make_kb())
    assert "developers" in prompt


def test_build_x_sub_agent_prompt_with_kb_contains_banned_topics():
    prompt = build_x_sub_agent_prompt(_make_kb())
    assert "politics" in prompt


def test_build_x_subagent_message_no_retry():
    msg = build_x_subagent_message(
        topic="SaaS pricing",
        angle="Year 1 mistakes",
        cmo_reasoning="High engagement topic",
        retry_context=None,
    )
    assert "Topic: SaaS pricing" in msg
    assert "Angle: Year 1 mistakes" in msg
    assert "CMO reasoning: High engagement topic" in msg
    assert "Previous attempt" not in msg


def test_build_x_subagent_message_with_retry_includes_context():
    msg = build_x_subagent_message(
        topic="SaaS pricing",
        angle="Year 1 mistakes",
        cmo_reasoning="High engagement topic",
        retry_context="post was too long, exceeded 270 chars",
    )
    assert "Previous attempt failed: post was too long, exceeded 270 chars" in msg
    assert "Try a different approach" in msg
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/nurma/vscode_projects/Marketer-Agent
pytest tests/test_x_sub_agent.py -v
```

Expected: `ImportError` — `build_x_sub_agent_prompt` and `build_x_subagent_message` don't exist yet.

- [ ] **Step 3: Add functions to `app/agents/prompts.py`**

Append after the existing `build_system_prompt` function (do not modify existing code):

```python
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


def build_x_subagent_message(
    topic: str,
    angle: str,
    cmo_reasoning: str,
    retry_context: str | None,
) -> str:
    parts = [
        f"Topic: {topic}",
        f"Angle: {angle}",
        f"CMO reasoning: {cmo_reasoning}",
    ]
    if retry_context:
        parts.append(f"Previous attempt failed: {retry_context}. Try a different approach.")
    return "\n".join(parts)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_x_sub_agent.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agents/prompts.py tests/test_x_sub_agent.py
git commit -m "feat: add X Sub-Agent prompt functions and tests"
```

---

### Task 2: Write `XSubAgentService` and tool factory

**Files:**
- Create: `app/agents/x_sub_agent_service.py`
- Test: `tests/test_x_sub_agent.py` (add one test for tool factory)

- [ ] **Step 1: Add tool factory test to `tests/test_x_sub_agent.py`**

Append to `tests/test_x_sub_agent.py`:

```python
from unittest.mock import AsyncMock, MagicMock


def test_make_invoke_x_sub_agent_tool_returns_tool_with_correct_name():
    from app.agents.x_sub_agent_service import make_invoke_x_sub_agent_tool

    mock_service = MagicMock()
    tool_fn = make_invoke_x_sub_agent_tool(mock_service)
    assert tool_fn.name == "invoke_x_sub_agent"


@pytest.mark.asyncio
async def test_make_invoke_x_sub_agent_tool_calls_service_run():
    from app.agents.x_sub_agent_service import make_invoke_x_sub_agent_tool
    from uuid import UUID

    mock_service = AsyncMock()
    mock_service.run.return_value = "Great post written"

    tool_fn = make_invoke_x_sub_agent_tool(mock_service)

    mock_runtime = MagicMock()
    mock_runtime.context.product_kb_id = 42

    # Call the underlying coroutine function directly, bypassing ToolRuntime injection
    post_idea_uuid = "12345678-1234-5678-1234-567812345678"
    result = await tool_fn.func(
        post_idea_id=post_idea_uuid,
        topic="SaaS pricing",
        angle="Year 1 mistakes",
        cmo_reasoning="High engagement",
        retry_context=None,
        runtime=mock_runtime,
    )

    assert mock_service.run.called
    call_kwargs = mock_service.run.call_args
    # message arg (positional 0) contains topic
    assert "SaaS pricing" in call_kwargs.args[0]
    # product_kb_id matches runtime context
    assert call_kwargs.args[2] == 42
    # post_idea_id is UUID
    assert call_kwargs.args[3] == UUID(post_idea_uuid)
    assert result == {"result": "Great post written"}
```

- [ ] **Step 2: Run new tests to confirm they fail**

```bash
pytest tests/test_x_sub_agent.py::test_make_invoke_x_sub_agent_tool_returns_tool_with_correct_name tests/test_x_sub_agent.py::test_make_invoke_x_sub_agent_tool_calls_service_run -v
```

Expected: `ModuleNotFoundError` — `x_sub_agent_service` doesn't exist yet.

- [ ] **Step 3: Create `app/agents/x_sub_agent_service.py`**

```python
from __future__ import annotations

import shlex
import time
from uuid import UUID, uuid4

import asyncpg
import structlog
from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import ToolRuntime, tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.pregel import Pregel

from app.agents.context import AgentContext
from app.agents.prompts import build_x_sub_agent_prompt, build_x_subagent_message
from app.config import Settings
from app.db.queries import get_product_kb
from app.logging_setup import ToolCallLogger
from app.tools.posts import create_post_draft, list_recent_posts
from app.tools.utm_builder import build_utm_url

log = structlog.get_logger()

_X_SUB_AGENT_MCP_SERVERS = ("web_search",)


class XSubAgentService:
    def __init__(self, settings: Settings, pool: asyncpg.Pool) -> None:
        self._settings = settings
        self._pool = pool
        self._agent: Pregel | None = None

    async def __aenter__(self) -> XSubAgentService:
        product_kb = await get_product_kb(self._pool)
        system_prompt = build_x_sub_agent_prompt(product_kb)
        mcp_tools = await self._build_mcp_client().get_tools()
        tools = mcp_tools + [build_utm_url, create_post_draft, list_recent_posts]
        self._agent = self._build_agent(tools, system_prompt)
        log.info("x_sub_agent_service_started", tools=[t.name for t in tools])
        return self

    async def __aexit__(self, *args: object) -> None:
        self._agent = None
        log.info("x_sub_agent_service_stopped")

    async def run(
        self,
        message: str,
        thread_id: str,
        product_kb_id: int,
        post_idea_id: UUID,
    ) -> str:
        assert self._agent is not None, "Call __aenter__ before run()"
        run_log = log.bind(
            component="x_sub_agent",
            run_id=str(uuid4()),
            thread_id=thread_id,
        )
        run_log.info("run_start")
        t0 = time.monotonic()

        tokens: list[str] = []
        async for event in self._agent.astream_events(
            {"messages": [{"role": "user", "content": message}]},
            config=self._agent_config(thread_id),
            context=AgentContext(product_kb_id=product_kb_id, post_idea_id=post_idea_id),
            version="v2",
        ):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    tokens.append(chunk.content)

        run_log.info("run_end", duration_ms=round((time.monotonic() - t0) * 1000))
        return "".join(tokens)

    def _build_mcp_client(self) -> MultiServerMCPClient:
        connections = {}
        for name in _X_SUB_AGENT_MCP_SERVERS:
            cmd = self._settings.mcp_command_for(name)
            parts = shlex.split(cmd)
            connections[name] = {
                "command": parts[0],
                "args": parts[1:],
                "transport": "stdio",
            }
        return MultiServerMCPClient(connections)

    def _build_agent(self, tools: list, system_prompt: str) -> Pregel:
        model = ChatAnthropic(
            model=self._settings.claude_model,
            api_key=self._settings.anthropic_api_key,
            temperature=self._settings.llm_temperature,
            max_tokens=self._settings.llm_max_tokens,
        )
        return create_agent(
            model,
            tools,
            system_prompt=system_prompt,
            checkpointer=InMemorySaver(),
            context_schema=AgentContext,
        )

    def _agent_config(self, thread_id: str) -> dict:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self._settings.sub_agent_max_iterations,
            "callbacks": [ToolCallLogger("x_sub_agent")],
        }


def make_invoke_x_sub_agent_tool(service: XSubAgentService):
    @tool
    async def invoke_x_sub_agent(
        post_idea_id: str,
        topic: str,
        angle: str,
        cmo_reasoning: str,
        retry_context: str | None,
        runtime: ToolRuntime[AgentContext],
    ) -> dict:
        """Delegate X post writing to X Sub-Agent. Returns the agent's final response."""
        thread_id = str(uuid4())
        message = build_x_subagent_message(topic, angle, cmo_reasoning, retry_context)
        result = await service.run(
            message,
            thread_id,
            runtime.context.product_kb_id,
            UUID(post_idea_id),
        )
        return {"result": result}

    return invoke_x_sub_agent
```

- [ ] **Step 4: Run all tests to confirm they pass**

```bash
pytest tests/test_x_sub_agent.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agents/x_sub_agent_service.py tests/test_x_sub_agent.py
git commit -m "feat: add XSubAgentService and invoke_x_sub_agent tool factory"
```

---

### Task 3: Create direct-invocation smoke test script

**Files:**
- Create: `scripts/test_x_subagent.py`

This script calls X Sub-Agent directly with a real `post_idea_id` from the DB — no CMO involved. It requires a running PostgreSQL with seed data and a real `post_idea` row. Before running: insert a `post_idea` manually or use one from a previous test run.

- [ ] **Step 1: Create `scripts/test_x_subagent.py`**

```python
"""
Smoke test: invoke X Sub-Agent directly with a manual post_idea.

Usage:
    python scripts/test_x_subagent.py <post_idea_id>

Requirements:
    - .env with DATABASE_URL and ANTHROPIC_API_KEY
    - A real post_idea row in the DB with state='open'
    - web_search MCP server available (TAVILY_API_KEY in .env)
"""
from __future__ import annotations

import asyncio
import sys
from uuid import UUID, uuid4

import asyncpg

from app.agents.prompts import build_x_subagent_message
from app.agents.x_sub_agent_service import XSubAgentService
from app.config import get_settings
from app.logging_setup import setup_logging


async def main(post_idea_id: str) -> None:
    setup_logging()
    settings = get_settings()

    async with asyncpg.create_pool(settings.database_url) as pool:
        idea = await pool.fetchrow(
            "SELECT product_kb_id, topic, angle, cmo_reasoning FROM post_ideas WHERE id = $1::uuid",
            post_idea_id,
        )
        if idea is None:
            print(f"post_idea {post_idea_id!r} not found in DB")
            sys.exit(1)

        async with XSubAgentService(settings, pool) as x_service:
            result = await x_service.run(
                message=build_x_subagent_message(
                    topic=idea["topic"],
                    angle=idea["angle"],
                    cmo_reasoning=idea["cmo_reasoning"],
                    retry_context=None,
                ),
                thread_id=str(uuid4()),
                product_kb_id=idea["product_kb_id"],
                post_idea_id=UUID(post_idea_id),
            )

    print("\n=== X Sub-Agent result ===")
    print(result)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/test_x_subagent.py <post_idea_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
```

- [ ] **Step 2: Verify script is importable (no syntax errors)**

```bash
python -c "import scripts.test_x_subagent" 2>&1 || python scripts/test_x_subagent.py --help 2>&1 | head -5
```

Expected: usage message or no output (not a traceback).

- [ ] **Step 3: Run full test suite to confirm nothing broken**

```bash
pytest tests/ -v --ignore=tests/test_mcp_web_search.py --ignore=tests/test_mcp_client.py -x
```

Expected: all tests PASS (MCP tests are excluded — they need external services).

- [ ] **Step 4: Commit**

```bash
git add scripts/test_x_subagent.py
git commit -m "feat: add X Sub-Agent direct invocation smoke test script"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] `XSubAgentService` with `__aenter__`/`__aexit__`/`run()` — Task 2
- [x] `run(self, message, thread_id, product_kb_id, post_idea_id)` argument order — Task 2
- [x] Tools: `web_search` MCP + `build_utm_url` + `create_post_draft` + `list_recent_posts` — Task 2
- [x] `InMemorySaver` + fresh `uuid4()` thread_id per call — Task 2
- [x] `build_x_sub_agent_prompt()` and `build_x_subagent_message()` — Task 1
- [x] `make_invoke_x_sub_agent_tool(service)` factory — Task 2
- [x] `retry_context` arg in `invoke_x_sub_agent` tool — Task 2
- [x] `recursion_limit` from `settings.sub_agent_max_iterations` — Task 2
- [x] `ToolCallLogger("x_sub_agent")` callback — Task 2
- [x] Direct invocation test script — Task 3

**Type consistency:**
- `run()` signature: `(self, message: str, thread_id: str, product_kb_id: int, post_idea_id: UUID) -> str` — consistent across Task 2 service, Task 2 tool factory, Task 3 script
- `build_x_sub_agent_prompt(product_kb: ProductKB | None)` — consistent with existing `build_system_prompt` pattern
- `make_invoke_x_sub_agent_tool` returns a `@tool` named `invoke_x_sub_agent` — consistent between Task 2 impl and Task 2 test
