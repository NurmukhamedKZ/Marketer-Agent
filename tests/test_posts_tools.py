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
