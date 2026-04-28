import pytest


@pytest.mark.asyncio
async def test_pool_connects(db_pool):
    async with db_pool.acquire() as conn:
        result = await conn.fetchval("SELECT 1")
    assert result == 1


@pytest.mark.asyncio
async def test_schema_tables_exist(db_pool):
    rows = await db_pool.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    names = {r["tablename"] for r in rows}
    assert {"product_kb", "signals", "post_ideas", "posts"}.issubset(names)


@pytest.mark.asyncio
async def test_post_state_enum_exists(db_pool):
    row = await db_pool.fetchrow(
        "SELECT typname FROM pg_type WHERE typname = 'post_state'"
    )
    assert row is not None


@pytest.mark.asyncio
async def test_signals_unique_constraint(db_pool):
    await db_pool.execute(
        """
        INSERT INTO signals (source, source_id, title, url, raw_json)
        VALUES ('reddit', 'abc123', 'Test title', 'https://example.com', '{}')
        ON CONFLICT (source, source_id) DO NOTHING
        """
    )
    await db_pool.execute(
        """
        INSERT INTO signals (source, source_id, title, url, raw_json)
        VALUES ('reddit', 'abc123', 'Duplicate', 'https://example.com', '{}')
        ON CONFLICT (source, source_id) DO NOTHING
        """
    )
    count = await db_pool.fetchval(
        "SELECT COUNT(*) FROM signals WHERE source_id = 'abc123'"
    )
    assert count == 1
