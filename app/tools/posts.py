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
