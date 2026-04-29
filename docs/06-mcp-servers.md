# MCP Servers (FastMCP)

Each MCP server is a small, focused FastMCP app with a few related tools. They run as separate systemd services and the agents connect to them via stdio (simplest) or HTTP transport.

## Tool Inventory

| MCP Server | Tools | Used by |
|------------|-------|---------|
| `signals` | `list_unused_signals(limit)`, `mark_signal_used(signal_id)`, `get_signal(signal_id)` | CMO |
| `posts` | `create_post_idea(...)`, `create_post_draft(...)`, `list_recent_posts(platform, limit)` | CMO, X Sub-Agent |
| `web_search` | `search(query, max_results)` | X Sub-Agent (for context, fact-checking) |
| `utm_builder` | `build_utm_url(base, source, medium, campaign, content)` | X Sub-Agent |

## Example: `signals_server.py`

```python
from fastmcp import FastMCP
from uuid import UUID
from mktg_agent.db import get_pool

mcp = FastMCP("signals")

@mcp.tool()
async def list_unused_signals(limit: int = 15) -> list[dict]:
    """
    Return up to `limit` recent, unused, non-expired signals from the signals table.
    Each signal contains: id, subreddit, title, body, url, score, created_at.
    """
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT id, subreddit, title, body, url, score, created_at
        FROM signals
        WHERE used = FALSE AND expires_at > NOW()
        ORDER BY created_at DESC
        LIMIT $1
    """, limit)
    return [dict(r) for r in rows]

@mcp.tool()
async def mark_signal_used(signal_id: str) -> dict:
    """Mark a signal as used so it won't be returned again."""
    pool = await get_pool()
    await pool.execute(
        "UPDATE signals SET used = TRUE WHERE id = $1",
        UUID(signal_id),
    )
    return {"ok": True, "signal_id": signal_id}

@mcp.tool()
async def get_signal(signal_id: str) -> dict | None:
    """Fetch a single signal by ID."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM signals WHERE id = $1",
        UUID(signal_id),
    )
    return dict(row) if row else None

if __name__ == "__main__":
    mcp.run()
```

## Example: `posts_server.py`

```python
from fastmcp import FastMCP
from mktg_agent.db import get_pool
from uuid import UUID

mcp = FastMCP("posts")

@mcp.tool()
async def create_post_idea(
    signal_id: str,
    target_platform: str,
    topic: str,
    angle: str,
    cmo_reasoning: str,
) -> dict:
    """
    Create a post_idea row. Returns the new post_idea's id.
    Called by the CMO Agent when it decides to act on a signal.
    """
    pool = await get_pool()
    row = await pool.fetchrow("""
        INSERT INTO post_ideas (signal_id, target_platform, topic, angle, cmo_reasoning)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
    """, UUID(signal_id), target_platform, topic, angle, cmo_reasoning)
    return {"post_idea_id": str(row["id"])}

@mcp.tool()
async def create_post_draft(
    post_idea_id: str,
    platform: str,
    draft_text: str,
    sub_agent_reasoning: str,
    utm_url: str | None = None,
) -> dict:
    """
    Create a posts row in state='draft' produced by a platform sub-agent.
    Returns the new post's id.
    """
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        idea = await conn.fetchrow(
            "SELECT signal_id FROM post_ideas WHERE id = $1",
            UUID(post_idea_id),
        )
        row = await conn.fetchrow("""
            INSERT INTO posts (
                platform, post_idea_id, signal_id, draft_text,
                sub_agent_reasoning, utm_url, state
            )
            VALUES ($1, $2, $3, $4, $5, $6, 'draft')
            RETURNING id
        """, platform, UUID(post_idea_id), idea["signal_id"],
              draft_text, sub_agent_reasoning, utm_url)
        await conn.execute(
            "UPDATE post_ideas SET state = 'consumed', consumed_at = NOW() WHERE id = $1",
            UUID(post_idea_id),
        )
    return {"post_id": str(row["id"])}

@mcp.tool()
async def list_recent_posts(platform: str, limit: int = 10) -> list[dict]:
    """List the N most recent posts on a given platform (for context / dedup)."""
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT id, draft_text, final_text, state, created_at
        FROM posts
        WHERE platform = $1
        ORDER BY created_at DESC
        LIMIT $2
    """, platform, limit)
    return [dict(r) for r in rows]

if __name__ == "__main__":
    mcp.run()
```

Other MCP servers (`product_kb_server.py`, `web_search_server.py`, `utm_builder_server.py`) follow the same pattern. The `web_search_server` wraps the Tavily API.
