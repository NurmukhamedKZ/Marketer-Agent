# Posts Tools + UTM Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `app/tools/posts.py` (4 @tool functions for CMO + X Sub-Agent) and `app/tools/utm_builder.py` (1 stateless @tool), plus `app/agents/context.py` (AgentContext) and `app/agents/mcp_client.py` (web_search loader stub).

**Architecture:** Each tool is a LangChain `@tool` function in the same process as the agent. DB context (`product_kb_id`, `signal_id`, `post_idea_id`) is injected at agent invocation time via `AgentContext` and read from `ToolRuntime` inside the tool — the LLM never sees these fields. DB logic is split into private `_*` functions so tests can call them directly without mocking ToolRuntime.

**Tech Stack:** `langchain` (`@tool`, `ToolRuntime`), `asyncpg` (pool from `app.db.pool.get_pool`), `urllib.parse` for UTM URL building, `langchain-mcp-adapters` (`MultiServerMCPClient`) for web_search.

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `app/agents/context.py` | CREATE | `AgentContext` dataclass — shared context for all agents |
| `app/tools/__init__.py` | CREATE | Package marker |
| `app/tools/posts.py` | CREATE | 4 @tool functions + private DB helpers |
| `app/tools/utm_builder.py` | CREATE | `build_utm_url` — stateless URL builder |
| `app/agents/mcp_client.py` | CREATE | `get_web_search_tools()` — loads web_search MCP tools |
| `tests/test_posts_tools.py` | CREATE | Integration tests for posts tools using db_pool fixture |
| `tests/test_utm_builder.py` | CREATE | Unit tests for build_utm_url |

---

## Task 1: AgentContext dataclass

**Files:**
- Create: `app/agents/context.py`
- Create: `app/agents/__init__.py` (if missing)

- [ ] **Step 1: Check if `__init__.py` exists in app/agents**

```bash
ls app/agents/
```

Expected: `cmo_agent.py  monitoring_agent.py` — no `__init__.py`, that's fine (namespace package).

- [ ] **Step 2: Create `app/agents/context.py`**

```python
from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class AgentContext:
    product_kb_id: int
    signal_id: UUID | None = field(default=None)
    post_idea_id: UUID | None = field(default=None)
```

- [ ] **Step 3: Verify import works**

```bash
python -c "from app.agents.context import AgentContext; c = AgentContext(product_kb_id=1); print(c)"
```

Expected: `AgentContext(product_kb_id=1, signal_id=None, post_idea_id=None)`

- [ ] **Step 4: Commit**

```bash
git add app/agents/context.py
git commit -m "feat: add AgentContext dataclass for tool runtime injection"
```

---

## Task 2: UTM Builder tool

**Files:**
- Create: `app/tools/__init__.py`
- Create: `app/tools/utm_builder.py`
- Create: `tests/test_utm_builder.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_utm_builder.py`:

```python
from app.tools.utm_builder import build_utm_url


def test_build_utm_url_contains_fixed_params():
    result = build_utm_url.invoke({
        "base_url": "https://example.com",
        "campaign": "saas-launch",
        "content": "pain-point",
    })
    assert "utm_source=x" in result
    assert "utm_medium=social" in result


def test_build_utm_url_contains_agent_params():
    result = build_utm_url.invoke({
        "base_url": "https://example.com",
        "campaign": "saas-launch",
        "content": "pain-point",
    })
    assert "utm_campaign=saas-launch" in result
    assert "utm_content=pain-point" in result


def test_build_utm_url_base_url_preserved():
    result = build_utm_url.invoke({
        "base_url": "https://myapp.io/landing",
        "campaign": "q1",
        "content": "angle",
    })
    assert result.startswith("https://myapp.io/landing")


def test_build_utm_url_existing_query_params_preserved():
    result = build_utm_url.invoke({
        "base_url": "https://example.com?ref=header",
        "campaign": "launch",
        "content": "cta",
    })
    assert "ref=header" in result
    assert "utm_source=x" in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_utm_builder.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.tools'`

- [ ] **Step 3: Create `app/tools/__init__.py`**

```python
```

(empty file)

- [ ] **Step 4: Create `app/tools/utm_builder.py`**

```python
from urllib.parse import urlencode, urlparse, parse_qs, urlunsplit, urlencode
from langchain.tools import tool

_UTM_SOURCE = "x"
_UTM_MEDIUM = "social"


@tool
def build_utm_url(base_url: str, campaign: str, content: str) -> str:
    """Build a UTM-tagged URL for an X post. source=x and medium=social are fixed."""
    parsed = urlparse(base_url)
    existing = parse_qs(parsed.query, keep_blank_values=True)
    existing.update({
        "utm_source": [_UTM_SOURCE],
        "utm_medium": [_UTM_MEDIUM],
        "utm_campaign": [campaign],
        "utm_content": [content],
    })
    query = urlencode({k: v[0] for k, v in existing.items()})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_utm_builder.py -v
```

Expected: 4 PASSED

- [ ] **Step 6: Commit**

```bash
git add app/tools/__init__.py app/tools/utm_builder.py tests/test_utm_builder.py
git commit -m "feat: add build_utm_url tool with fixed source=x, medium=social"
```

---

## Task 3: Posts tools — `create_post_idea`

**Files:**
- Create: `app/tools/posts.py`
- Create: `tests/test_posts_tools.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_posts_tools.py`:

```python
import pytest
from uuid import uuid4
import asyncpg

from app.tools.posts import _insert_post_idea


@pytest.mark.asyncio
async def test_create_post_idea_inserts_row(db_pool: asyncpg.Pool, seed_ids: tuple[int, int]):
    _, product_kb_id = seed_ids

    # Insert a signal to reference
    signal_id = await db_pool.fetchval("""
        INSERT INTO signals (product_kb_id, source, source_id, title, url, raw_json)
        VALUES ($1, 'reddit', $2, 'Test signal', 'https://reddit.com/test', '{}')
        RETURNING id
    """, product_kb_id, str(uuid4()))

    result = await _insert_post_idea(
        pool=db_pool,
        product_kb_id=product_kb_id,
        signal_id=signal_id,
        topic="SaaS deployment",
        angle="pain point",
        cmo_reasoning="High engagement post",
        target_platform="x",
    )

    assert "post_idea_id" in result
    row = await db_pool.fetchrow("SELECT * FROM post_ideas WHERE id = $1::uuid", result["post_idea_id"])
    assert row["topic"] == "SaaS deployment"
    assert row["state"] == "open"
    assert row["product_kb_id"] == product_kb_id
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_posts_tools.py::test_create_post_idea_inserts_row -v
```

Expected: `ImportError: cannot import name '_insert_post_idea'`

- [ ] **Step 3: Create `app/tools/posts.py` with `_insert_post_idea` and `create_post_idea`**

```python
from uuid import UUID

import asyncpg
from langchain.tools import tool, ToolRuntime

from app.agents.context import AgentContext
from app.db.pool import get_pool


async def _insert_post_idea(
    pool: asyncpg.Pool,
    product_kb_id: int,
    signal_id: UUID | None,
    topic: str,
    angle: str,
    cmo_reasoning: str,
    target_platform: str,
) -> dict:
    row = await pool.fetchrow(
        """
        INSERT INTO post_ideas (product_kb_id, signal_id, topic, angle, cmo_reasoning, target_platform)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        product_kb_id, signal_id, topic, angle, cmo_reasoning, target_platform,
    )
    return {"post_idea_id": str(row["id"])}


@tool
async def create_post_idea(
    topic: str,
    angle: str,
    cmo_reasoning: str,
    target_platform: str,
    runtime: ToolRuntime[AgentContext],
) -> dict:
    """Save the CMO's strategic decision for a signal. Returns post_idea_id."""
    pool = await get_pool()
    return await _insert_post_idea(
        pool,
        runtime.context.product_kb_id,
        runtime.context.signal_id,
        topic, angle, cmo_reasoning, target_platform,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_posts_tools.py::test_create_post_idea_inserts_row -v
```

Expected: PASSED

- [ ] **Step 5: Commit**

```bash
git add app/tools/posts.py tests/test_posts_tools.py
git commit -m "feat: add create_post_idea tool with DB insertion"
```

---

## Task 4: Posts tools — `list_recent_posts` + `get_post`

**Files:**
- Modify: `app/tools/posts.py`
- Modify: `tests/test_posts_tools.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_posts_tools.py`:

```python
from app.tools.posts import _list_recent_posts, _get_post


@pytest.mark.asyncio
async def test_list_recent_posts_returns_posts(db_pool: asyncpg.Pool, seed_ids: tuple[int, int]):
    _, product_kb_id = seed_ids

    signal_id = await db_pool.fetchval("""
        INSERT INTO signals (product_kb_id, source, source_id, title, url, raw_json)
        VALUES ($1, 'reddit', $2, 'List test signal', 'https://reddit.com/list', '{}')
        RETURNING id
    """, product_kb_id, str(uuid4()))

    idea_id = await db_pool.fetchval("""
        INSERT INTO post_ideas (product_kb_id, signal_id, topic, angle, cmo_reasoning, target_platform)
        VALUES ($1, $2, 'topic', 'angle', 'reason', 'x')
        RETURNING id
    """, product_kb_id, signal_id)

    await db_pool.execute("""
        INSERT INTO posts (product_kb_id, platform, post_idea_id, signal_id, draft_text)
        VALUES ($1, 'x', $2, $3, 'Draft post text')
    """, product_kb_id, idea_id, signal_id)

    result = await _list_recent_posts(pool=db_pool, product_kb_id=product_kb_id, platform="x", limit=5)

    assert len(result) >= 1
    assert result[0]["draft_text"] == "Draft post text"


@pytest.mark.asyncio
async def test_list_recent_posts_filters_by_product_kb(db_pool: asyncpg.Pool, seed_ids: tuple[int, int]):
    _, product_kb_id = seed_ids
    result = await _list_recent_posts(pool=db_pool, product_kb_id=999999, platform="x", limit=5)
    assert result == []


@pytest.mark.asyncio
async def test_get_post_returns_row(db_pool: asyncpg.Pool, seed_ids: tuple[int, int]):
    _, product_kb_id = seed_ids

    signal_id = await db_pool.fetchval("""
        INSERT INTO signals (product_kb_id, source, source_id, title, url, raw_json)
        VALUES ($1, 'reddit', $2, 'Get test signal', 'https://reddit.com/get', '{}')
        RETURNING id
    """, product_kb_id, str(uuid4()))

    idea_id = await db_pool.fetchval("""
        INSERT INTO post_ideas (product_kb_id, signal_id, topic, angle, cmo_reasoning, target_platform)
        VALUES ($1, $2, 'topic', 'angle', 'reason', 'x')
        RETURNING id
    """, product_kb_id, signal_id)

    post_id = await db_pool.fetchval("""
        INSERT INTO posts (product_kb_id, platform, post_idea_id, signal_id, draft_text)
        VALUES ($1, 'x', $2, $3, 'Get me by id')
        RETURNING id
    """, product_kb_id, idea_id, signal_id)

    result = await _get_post(pool=db_pool, post_id=str(post_id))
    assert result is not None
    assert result["draft_text"] == "Get me by id"


@pytest.mark.asyncio
async def test_get_post_returns_none_for_missing(db_pool: asyncpg.Pool):
    result = await _get_post(pool=db_pool, post_id=str(uuid4()))
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_posts_tools.py -k "list_recent or get_post" -v
```

Expected: `ImportError: cannot import name '_list_recent_posts'`

- [ ] **Step 3: Add `_list_recent_posts`, `list_recent_posts`, `_get_post`, `get_post` to `app/tools/posts.py`**

Append to `app/tools/posts.py`:

```python
async def _list_recent_posts(
    pool: asyncpg.Pool,
    product_kb_id: int,
    platform: str,
    limit: int,
) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT id, draft_text, final_text, state, created_at
        FROM posts
        WHERE product_kb_id = $1 AND platform = $2
        ORDER BY created_at DESC
        LIMIT $3
        """,
        product_kb_id, platform, limit,
    )
    return [dict(r) for r in rows]


@tool
async def list_recent_posts(
    platform: str,
    limit: int,
    runtime: ToolRuntime[AgentContext],
) -> list[dict]:
    """List the N most recent posts on a platform for deduplication context."""
    pool = await get_pool()
    return await _list_recent_posts(pool, runtime.context.product_kb_id, platform, limit)


async def _get_post(pool: asyncpg.Pool, post_id: str) -> dict | None:
    row = await pool.fetchrow(
        "SELECT * FROM posts WHERE id = $1::uuid",
        post_id,
    )
    return dict(row) if row else None


@tool
async def get_post(post_id: str) -> dict | None:
    """Fetch a single post by ID."""
    pool = await get_pool()
    return await _get_post(pool, post_id)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_posts_tools.py -k "list_recent or get_post" -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add app/tools/posts.py tests/test_posts_tools.py
git commit -m "feat: add list_recent_posts and get_post tools"
```

---

## Task 5: Posts tools — `create_post_draft` (transaction)

**Files:**
- Modify: `app/tools/posts.py`
- Modify: `tests/test_posts_tools.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_posts_tools.py`:

```python
from app.tools.posts import _insert_post_draft


@pytest.mark.asyncio
async def test_create_post_draft_inserts_post(db_pool: asyncpg.Pool, seed_ids: tuple[int, int]):
    _, product_kb_id = seed_ids

    signal_id = await db_pool.fetchval("""
        INSERT INTO signals (product_kb_id, source, source_id, title, url, raw_json)
        VALUES ($1, 'reddit', $2, 'Draft signal', 'https://reddit.com/draft', '{}')
        RETURNING id
    """, product_kb_id, str(uuid4()))

    idea_id = await db_pool.fetchval("""
        INSERT INTO post_ideas (product_kb_id, signal_id, topic, angle, cmo_reasoning, target_platform)
        VALUES ($1, $2, 'Deploy SaaS', 'pain', 'reason', 'x')
        RETURNING id
    """, product_kb_id, signal_id)

    result = await _insert_post_draft(
        pool=db_pool,
        product_kb_id=product_kb_id,
        post_idea_id=idea_id,
        draft_text="Have you tried deploying on Railway?",
        sub_agent_reasoning="Matches the ICP pain point",
        utm_url="https://myapp.com?utm_source=x&utm_medium=social&utm_campaign=deploy",
    )

    assert "post_id" in result
    post = await db_pool.fetchrow("SELECT * FROM posts WHERE id = $1::uuid", result["post_id"])
    assert post["draft_text"] == "Have you tried deploying on Railway?"
    assert post["state"] == "draft"
    assert post["signal_id"] == signal_id


@pytest.mark.asyncio
async def test_create_post_draft_marks_idea_consumed(db_pool: asyncpg.Pool, seed_ids: tuple[int, int]):
    _, product_kb_id = seed_ids

    signal_id = await db_pool.fetchval("""
        INSERT INTO signals (product_kb_id, source, source_id, title, url, raw_json)
        VALUES ($1, 'reddit', $2, 'Consumed signal', 'https://reddit.com/consumed', '{}')
        RETURNING id
    """, product_kb_id, str(uuid4()))

    idea_id = await db_pool.fetchval("""
        INSERT INTO post_ideas (product_kb_id, signal_id, topic, angle, cmo_reasoning, target_platform)
        VALUES ($1, $2, 'topic', 'angle', 'reason', 'x')
        RETURNING id
    """, product_kb_id, signal_id)

    await _insert_post_draft(
        pool=db_pool,
        product_kb_id=product_kb_id,
        post_idea_id=idea_id,
        draft_text="Post text",
        sub_agent_reasoning="reason",
        utm_url=None,
    )

    idea = await db_pool.fetchrow("SELECT state, consumed_at FROM post_ideas WHERE id = $1", idea_id)
    assert idea["state"] == "consumed"
    assert idea["consumed_at"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_posts_tools.py -k "post_draft" -v
```

Expected: `ImportError: cannot import name '_insert_post_draft'`

- [ ] **Step 3: Add `_insert_post_draft` and `create_post_draft` to `app/tools/posts.py`**

Append to `app/tools/posts.py`:

```python
async def _insert_post_draft(
    pool: asyncpg.Pool,
    product_kb_id: int,
    post_idea_id: UUID,
    draft_text: str,
    sub_agent_reasoning: str,
    utm_url: str | None,
) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            idea = await conn.fetchrow(
                "SELECT signal_id FROM post_ideas WHERE id = $1",
                post_idea_id,
            )
            row = await conn.fetchrow(
                """
                INSERT INTO posts (
                    product_kb_id, platform, post_idea_id, signal_id,
                    draft_text, sub_agent_reasoning, utm_url, state
                )
                VALUES ($1, 'x', $2, $3, $4, $5, $6, 'draft')
                RETURNING id
                """,
                product_kb_id, post_idea_id, idea["signal_id"],
                draft_text, sub_agent_reasoning, utm_url,
            )
            await conn.execute(
                "UPDATE post_ideas SET state = 'consumed', consumed_at = NOW() WHERE id = $1",
                post_idea_id,
            )
    return {"post_id": str(row["id"])}


@tool
async def create_post_draft(
    draft_text: str,
    sub_agent_reasoning: str,
    utm_url: str | None,
    runtime: ToolRuntime[AgentContext],
) -> dict:
    """Save the draft post and mark the post_idea as consumed. Returns post_id."""
    pool = await get_pool()
    return await _insert_post_draft(
        pool,
        runtime.context.product_kb_id,
        runtime.context.post_idea_id,
        draft_text, sub_agent_reasoning, utm_url,
    )
```

- [ ] **Step 4: Run all posts tests to verify they pass**

```bash
python -m pytest tests/test_posts_tools.py -v
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add app/tools/posts.py tests/test_posts_tools.py
git commit -m "feat: add create_post_draft tool with transactional post_idea consumption"
```

---

## Task 6: MCP client stub for web_search

**Files:**
- Create: `app/agents/mcp_client.py`

No test — this module can only be exercised end-to-end when web_search MCP server is implemented (step 6 of the project plan).

- [ ] **Step 1: Create `app/agents/mcp_client.py`**

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.tools import BaseTool

from app.config import get_settings


async def get_web_search_tools() -> list[BaseTool]:
    """Load web_search MCP tools via stdio. Requires web_search server to be implemented."""
    settings = get_settings()
    client = MultiServerMCPClient({
        "web_search": {
            "command": "python",
            "args": ["-m", "app.mcp.web_search"],
            "transport": "stdio",
        }
    })
    return await client.get_tools()
```

- [ ] **Step 2: Verify import works**

```bash
python -c "from app.agents.mcp_client import get_web_search_tools; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/agents/mcp_client.py
git commit -m "feat: add mcp_client stub for web_search tool loading"
```

---

## Task 7: Update CLAUDE.md implementation plan table

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Mark step 5 as done in the plan table**

In `CLAUDE.md`, find the plan table and update step 5:

```markdown
| 5 | posts MCP сервер + utm_builder MCP сервер + тесты | ✅ Готово |
```

Note: Step 5 was redesigned — implemented as `@tool` functions in `app/tools/` instead of MCP servers.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "chore: mark step 5 complete in implementation plan"
```

---

## Self-Review

**Spec coverage:**
- ✅ `AgentContext` with `product_kb_id`, `signal_id`, `post_idea_id` — Task 1
- ✅ `create_post_idea` (hidden: `product_kb_id`, `signal_id`) — Task 3
- ✅ `create_post_draft` (transaction, hidden: `product_kb_id`, `post_idea_id`) — Task 5
- ✅ `list_recent_posts` (filtered by `product_kb_id`) — Task 4
- ✅ `get_post` (by UUID) — Task 4
- ✅ `build_utm_url` (stateless, fixed source/medium) — Task 2
- ✅ `mcp_client.py` (web_search stub) — Task 6
- ✅ Tests for hidden fields absent from schema — not explicitly tested (ToolRuntime handles this automatically by LangChain)

**Type consistency:**
- `_insert_post_idea` → returns `dict` with key `"post_idea_id"` → used in test as `result["post_idea_id"]` ✅
- `_insert_post_draft` → returns `dict` with key `"post_id"` → used in test as `result["post_id"]` ✅
- `_list_recent_posts` → returns `list[dict]` ✅
- `_get_post` → returns `dict | None` ✅
- `post_idea_id` in `_insert_post_draft` is `UUID` type → passed as `UUID` from context ✅
