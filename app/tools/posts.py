from uuid import UUID

import asyncpg
from langchain.tools import tool

from app.agents.context import current_product_kb_id, current_signal_id
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
) -> dict:
    """Save the CMO's strategic decision for a signal. Returns post_idea_id."""
    pool = await get_pool()
    return await _insert_post_idea(
        pool,
        current_product_kb_id.get(),
        current_signal_id.get(),
        topic, angle, cmo_reasoning, target_platform,
    )


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
) -> list[dict]:
    """List the N most recent posts on a platform for deduplication context."""
    pool = await get_pool()
    return await _list_recent_posts(pool, current_product_kb_id.get(), platform, limit)


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
