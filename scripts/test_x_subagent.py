"""
Smoke test: invoke X Sub-Agent directly with a manual post_idea.

Usage:
    PYTHONPATH=. python scripts/test_x_subagent.py <post_idea_id>

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
