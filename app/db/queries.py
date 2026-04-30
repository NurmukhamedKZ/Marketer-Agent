from dataclasses import dataclass
from typing import Any
import asyncpg

from app.models.post import Post
from app.models.post_idea import PostIdea
from app.models.product_kb import ProductKB
from app.models.signal import Signal


async def fetch_one(
    pool: asyncpg.Pool, query: str, *args: Any
) -> asyncpg.Record | None:
    return await pool.fetchrow(query, *args)


async def fetch_all(
    pool: asyncpg.Pool, query: str, *args: Any
) -> list[asyncpg.Record]:
    return await pool.fetch(query, *args)


async def execute(pool: asyncpg.Pool, query: str, *args: Any) -> str:
    return await pool.execute(query, *args)


async def get_product_kb(pool: asyncpg.Pool) -> ProductKB | None:
    row = await pool.fetchrow("SELECT * FROM product_kb LIMIT 1")
    return ProductKB(**dict(row)) if row else None


@dataclass
class AgentPromptContext:
    signals: list[Signal]
    open_ideas: list[PostIdea]
    recent_approved: list[Post]
    recent_rejected: list[Post]


async def fetch_agent_prompt_context(
    pool: asyncpg.Pool, product_kb_id: int
) -> AgentPromptContext:
    signals_rows = await pool.fetch(
        """
        SELECT *
        FROM signals
        WHERE product_kb_id = $1
          AND used = FALSE
          AND expires_at > NOW()
        ORDER BY score DESC NULLS LAST, created_at DESC
        LIMIT 10
        """,
        product_kb_id,
    )
    ideas_rows = await pool.fetch(
        """
        SELECT *
        FROM post_ideas
        WHERE product_kb_id = $1 AND state = 'open'
        ORDER BY created_at DESC
        LIMIT 5
        """,
        product_kb_id,
    )
    approved_rows = await pool.fetch(
        """
        SELECT *
        FROM posts
        WHERE product_kb_id = $1 AND state IN ('approved', 'published')
        ORDER BY created_at DESC
        LIMIT 5
        """,
        product_kb_id,
    )
    rejected_rows = await pool.fetch(
        """
        SELECT *
        FROM posts
        WHERE product_kb_id = $1 AND state = 'rejected'
        ORDER BY created_at DESC
        LIMIT 5
        """,
        product_kb_id,
    )
    return AgentPromptContext(
        signals=[Signal(**dict(r)) for r in signals_rows],
        open_ideas=[PostIdea(**dict(r)) for r in ideas_rows],
        recent_approved=[Post(**dict(r)) for r in approved_rows],
        recent_rejected=[Post(**dict(r)) for r in rejected_rows],
    )
