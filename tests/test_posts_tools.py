import pytest
from uuid import uuid4
import asyncpg

from app.tools.posts import _insert_post_idea, _list_recent_posts, _get_post, _insert_post_draft


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
