from uuid import UUID

import asyncpg
from langchain.tools import tool, ToolRuntime
from typing import Literal

from app.agents.context import AgentContext
from app.db.pool import get_pool


platforms = Literal["x","reddit", "linkedin", "instagram", "tiktok"]


async def _insert_post_idea(
    pool: asyncpg.Pool,
    product_kb_id: int,
    signal_id: UUID | None,
    topic: str,
    angle: str,
    cmo_reasoning: str,
    target_platform: platforms,
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
    target_platform: platforms,
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


async def _list_recent_posts(
    pool: asyncpg.Pool,
    product_kb_id: int,
    platform: platforms,
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
    platform: platforms,
    limit: int,
    runtime: ToolRuntime[AgentContext],
) -> list[dict]:
    """List the N most recent posts on a platform for deduplication context."""
    pool = await get_pool()
    return await _list_recent_posts(pool, runtime.context.product_kb_id, platform, limit)


async def _get_post(pool: asyncpg.Pool, post_id: str) -> dict | None:
    row = await pool.fetchrow(
        """
        SELECT id, platform, post_idea_id, signal_id, draft_text, final_text,
               sub_agent_reasoning, state, utm_url, created_at, updated_at
        FROM posts WHERE id = $1::uuid
        """,
        post_id,
    )
    return dict(row) if row else None


@tool
async def get_post(post_id: str) -> dict | None:
    """Fetch a single post by ID."""
    pool = await get_pool()
    return await _get_post(pool, post_id)


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
            if idea is None:
                raise ValueError(f"post_idea {post_idea_id} not found")
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
