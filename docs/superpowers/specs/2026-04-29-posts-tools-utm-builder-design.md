---
title: Posts Tools + UTM Builder Design
date: 2026-04-29
status: approved
---

# Posts Tools + UTM Builder — Design Spec

## Context

Step 5 of the implementation plan. Originally specified as two MCP servers (`posts_server.py`, `utm_builder_server.py`). During design review, the team decided to use LangChain `@tool` functions instead of MCP for both, since the complexity of stdio processes + interceptors + schema hiding is not justified for these in-process tools.

`web_search` remains an MCP server (already implemented in `app/mcp/web_search.py`).

---

## Architecture Decision: `@tool` over MCP

MCP servers make sense for `web_search` because it wraps an external API that benefits from process isolation. For posts and UTM, the tools are just DB operations and URL construction — same process as the agent is the right call.

**Before (MCP approach):**
- Separate processes, stdio transport, `langchain-mcp-adapters`, interceptors, `hide_context_params` — ~150 lines of infrastructure

**After (`@tool` approach):**
- Functions decorated with `@tool`, `ToolRuntime[AgentContext]` for hidden context, direct asyncpg pool — minimal boilerplate

---

## File Structure

```
app/
  tools/
    posts.py        # 4 @tool functions for CMO + X Sub-Agent
    utm_builder.py  # 1 @tool function, stateless
  mcp/
    web_search.py   # FastMCP server (existing, unchanged)
  agents/
    context.py      # AgentContext dataclass
    mcp_client.py   # loads web_search MCP tools only, no interceptors
```

---

## AgentContext (`app/agents/context.py`)

```python
from dataclasses import dataclass
from uuid import UUID

@dataclass
class AgentContext:
    product_kb_id: int
    signal_id: UUID | None = None     # CMO sets this after selecting a signal
    post_idea_id: UUID | None = None  # X Sub-Agent receives this from CMO
```

- `product_kb_id` — always present, set at agent startup from DB seed
- `signal_id` — set by CMO Agent when it selects a signal to act on
- `post_idea_id` — set when CMO invokes X Sub-Agent for a specific post_idea

---

## `app/tools/posts.py` — 4 tools

All tools that write to DB use `ToolRuntime[AgentContext]` to read hidden context fields. The LLM never sees `product_kb_id`, `signal_id`, or `post_idea_id` in the tool schema.

### `create_post_idea`

Called by: CMO Agent  
Hidden fields: `product_kb_id`, `signal_id`

```python
@tool
async def create_post_idea(
    topic: str,
    angle: str,
    cmo_reasoning: str,
    target_platform: str,
    runtime: ToolRuntime[AgentContext],
) -> dict:
    """Save the CMO's strategic decision for a signal. Returns post_idea_id."""
```

Inserts into `post_ideas`. Returns `{"post_idea_id": str}`.

### `create_post_draft`

Called by: X Sub-Agent  
Hidden fields: `product_kb_id`, `post_idea_id`

```python
@tool
async def create_post_draft(
    draft_text: str,
    sub_agent_reasoning: str,
    utm_url: str | None,
    runtime: ToolRuntime[AgentContext],
) -> dict:
    """Save the draft post and mark the post_idea as consumed. Returns post_id."""
```

Single transaction:
1. `SELECT signal_id FROM post_ideas WHERE id = $post_idea_id` — to carry signal_id into posts
2. `INSERT INTO posts (state='draft', signal_id=..., ...)`
3. `UPDATE post_ideas SET state='consumed', consumed_at=NOW()`

Returns `{"post_id": str}`.

### `list_recent_posts`

Called by: X Sub-Agent  
Hidden fields: `product_kb_id`

```python
@tool
async def list_recent_posts(
    platform: str,
    limit: int,
    runtime: ToolRuntime[AgentContext],
) -> list[dict]:
    """List the N most recent posts for deduplication. Returns id, draft_text, state, created_at."""
```

### `get_post`

Called by: X Sub-Agent  
Hidden fields: none (post_id uniquely identifies the row)

```python
@tool
async def get_post(post_id: str) -> dict | None:
    """Fetch a single post by ID."""
```

---

## `app/tools/utm_builder.py` — 1 tool

Stateless — no DB, no `ToolRuntime`. `source` and `medium` are fixed constants.

```python
SOURCE = "x"
MEDIUM = "social"

@tool
def build_utm_url(base_url: str, campaign: str, content: str) -> str:
    """
    Build a UTM-tagged URL for an X post.
    source=x and medium=social are fixed. Agent provides campaign and content.
    Example: build_utm_url("https://myapp.com", "saas-launch", "pain-point-angle")
    """
```

Returns: `https://myapp.com?utm_source=x&utm_medium=social&utm_campaign=saas-launch&utm_content=pain-point-angle`

`campaign` — strategic campaign name (e.g., `saas-launch`, `q1-growth`)  
`content` — differentiates posts within the campaign (e.g., angle slug or post_id)

---

## `app/agents/mcp_client.py`

Loads only `web_search` MCP tools. No interceptors, no schema hiding.

```python
async def get_web_search_tools() -> list[BaseTool]:
    client = MultiServerMCPClient({
        "web_search": {
            "command": "python",
            "args": ["-m", "app.mcp.web_search"],
            "transport": "stdio",
        }
    })
    return await client.get_tools()
```

---

## Tool Assembly for Agents

```python
# CMO Agent tools
mcp_tools = await get_web_search_tools()
cmo_tools = [create_post_idea, list_recent_posts] + mcp_tools

# X Sub-Agent tools
mcp_tools = await get_web_search_tools()
x_tools = [create_post_draft, list_recent_posts, get_post, build_utm_url] + mcp_tools
```

---

## Agent Invocation with Context

```python
# CMO Agent — after selecting a signal
context = AgentContext(product_kb_id=product_kb_id, signal_id=selected_signal_id)
await cmo_agent.ainvoke({"messages": [...]}, context=context)

# X Sub-Agent — after CMO creates a post_idea
context = AgentContext(product_kb_id=product_kb_id, post_idea_id=created_idea_id)
await x_sub_agent.ainvoke({"messages": [...]}, context=context)
```

---

## Testing

- Unit tests for `build_utm_url` — pure function, no mocks needed
- Unit tests for posts tools — mock asyncpg pool, assert correct SQL params
- Integration test for `create_post_draft` transaction — verify post_idea state transitions to `consumed`
- Test that hidden fields (`product_kb_id`, `signal_id`, `post_idea_id`) are absent from tool schemas

---

## What This Spec Does NOT Cover

- CMO Agent signal selection logic (covered in agents spec)
- X Sub-Agent post writing logic (covered in agents spec)
- `web_search.py` MCP server internals (already implemented)
- Telegram approval flow (step 9)
