# X Sub-Agent Design

**Date:** 2026-04-30  
**Status:** Approved  
**Task:** Step 9 — X Sub-Agent, call directly with manual post_idea

---

## Overview

X Sub-Agent is a focused LangChain agent responsible for writing a single X (Twitter) post given a strategic brief from the CMO Agent. It is invoked as a `@tool` by the CMO Agent, making the CMO the orchestrator and X Sub-Agent the tactician.

---

## Architecture

### Files

| File | Purpose |
|---|---|
| `app/agents/x_sub_agent_service.py` | `XSubAgentService` class + `make_invoke_x_sub_agent_tool()` factory |
| `app/agents/prompts.py` | Add `build_x_sub_agent_prompt()` and `build_x_subagent_message()` |
| `scripts/test_x_subagent.py` | Manual test script — calls sub-agent directly with hardcoded post_idea |

### Tools available to X Sub-Agent

| Tool | Type | Purpose |
|---|---|---|
| `web_search` | MCP stdio | Research trending angles, verify claims |
| `build_utm_url` | `@tool` in-process | Build tracking URL before saving draft |
| `list_recent_posts` | `@tool` in-process | Deduplication — check recent posts |
| `create_post_draft` | `@tool` in-process | Save draft and mark post_idea as consumed — final action |

---

## Service Class: `XSubAgentService`

Same lifecycle pattern as `CMOAgentService`.

```python
class XSubAgentService:
    def __init__(self, settings: Settings, pool: asyncpg.Pool) -> None:
        # only saves dependencies, no I/O

    async def __aenter__(self) -> XSubAgentService:
        # 1. Build system prompt (with product_kb injected)
        # 2. Load MCP tools: web_search via MultiServerMCPClient
        # 3. Combine with @tool functions: build_utm_url, create_post_draft, list_recent_posts
        # 4. create_agent(model, tools, system_prompt=..., checkpointer=InMemorySaver(), context_schema=AgentContext)

    async def __aexit__(self, *args) -> None: ...

    async def run(
        self,
        thread_id: str,
        message: str,
        product_kb_id: int,
        post_idea_id: UUID,
    ) -> str:
        # astream_events with context=AgentContext(product_kb_id=..., post_idea_id=...)
        # collects all tokens → returns full str (not AsyncIterator)
        # CMO waits for completion before next step
```

**Why `run()` returns `str` not `AsyncIterator`:** This is an internal agent-to-agent call. The CMO needs the complete result to decide next steps. Streaming is only needed at the user-facing boundary (Telegram, HTTP).

**Checkpointing:** `InMemorySaver` + fresh `uuid4()` thread_id per `invoke_x_sub_agent` call. Each call is fully independent. CMO orchestrates retries through messages, not shared memory — this keeps sub-agent history clean on each attempt.

---

## Tool Factory: `make_invoke_x_sub_agent_tool`

```python
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
        """Delegate X post writing to X Sub-Agent. Returns post_id on success."""
        thread_id = str(uuid4())
        message = build_x_subagent_message(topic, angle, cmo_reasoning, retry_context)
        result = await service.run(
            thread_id, message,
            runtime.context.product_kb_id,
            UUID(post_idea_id),
        )
        return {"result": result}
    return invoke_x_sub_agent
```

**Why a factory and not `AgentContext`:** Putting `XSubAgentService` in `AgentContext` would cause a circular import (`context.py` ↔ `x_sub_agent_service.py`) and mix data context with service dependencies. Factory closure is the clean solution.

**Why CMO passes `topic/angle/cmo_reasoning` explicitly:** CMO LLM already holds this context (it just created the post_idea). No extra DB round-trip needed. `retry_context` gives CMO a clean channel to explain what failed on retry.

---

## Prompts

### System prompt (`_X_SUB_AGENT_SYSTEM_PROMPT`)

```
You are an expert X (Twitter) copywriter.

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
Do not output anything after.
```

Product KB section is appended via `build_x_sub_agent_prompt(product_kb)` — same `_PRODUCT_KB_SECTION` template as CMO.

### First message (`build_x_subagent_message`)

```python
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

---

## Lifecycle: how XSubAgentService lives alongside CMO

**Step 9 (this task):** `XSubAgentService` is called directly via test script. CMO is not involved.

**Step 12 (future):** `CMOAgentService` will be extended to accept `extra_tools` so it receives `invoke_x_sub_agent` at init time:

```python
# Entry point (Telegram bot or FastAPI) — step 12
async with XSubAgentService(settings, pool) as x_service:
    invoke_tool = make_invoke_x_sub_agent_tool(x_service)
    async with CMOAgentService(settings, pool, extra_tools=[invoke_tool]) as cmo:
        dp["cmo"] = cmo
        await dp.start_polling()
```

One instance per process. Both services share the same process lifecycle.

---

## Error flow (CMO orchestrates retry)

```
CMO → invoke_x_sub_agent(post_idea_id, topic, angle, ..., retry_context=None)
    → X Sub-Agent runs → fails (e.g., create_post_draft raises)
    → tool returns {"error": "..."}
CMO sees error → calls invoke_x_sub_agent again with retry_context="previous attempt failed because X, try different angle"
    → X Sub-Agent runs fresh (new thread_id, clean history)
```

No shared state between attempts. CMO message carries all context needed.

---

## Test Script: `scripts/test_x_subagent.py`

Calls X Sub-Agent directly without CMO — step 9 goal.

```python
async def main():
    settings = get_settings()
    async with asyncpg.create_pool(settings.database_url) as pool:
        async with XSubAgentService(settings, pool) as x_service:
            result = await x_service.run(
                thread_id=str(uuid4()),
                message=build_x_subagent_message(
                    topic="SaaS pricing mistakes",
                    angle="What founders get wrong in year 1",
                    cmo_reasoning="High engagement topic in our ICP",
                    retry_context=None,
                ),
                product_kb_id=1,          # hardcoded for MVP
                post_idea_id=UUID("..."), # real ID from DB
            )
            print(result)
```

---

## Parallel invocation

Multiple concurrent `invoke_x_sub_agent` calls are safe:
- Each call uses a unique `thread_id` → `InMemorySaver` isolates state per thread
- MCP tool calls each open their own stdio session automatically (per langchain-mcp-adapters design)
- No shared mutable state in `XSubAgentService` after `__aenter__`
