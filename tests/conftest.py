import asyncio
import pathlib
import pytest
import asyncpg
from app.config import get_settings, Settings
from app.db.setup import ensure_seed_data

_TEST_DB = "mktg_agent_test"


def _base_url(database_url: str) -> str:
    return database_url.rsplit("/", 1)[0]


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def db_pool():
    settings = get_settings()
    sys_url = _base_url(settings.database_url) + "/postgres"

    sys_conn = await asyncpg.connect(sys_url)
    await sys_conn.execute(f"DROP DATABASE IF EXISTS {_TEST_DB}")
    await sys_conn.execute(f"CREATE DATABASE {_TEST_DB}")
    await sys_conn.close()

    test_url = _base_url(settings.database_url) + f"/{_TEST_DB}"
    pool = await asyncpg.create_pool(test_url, min_size=1, max_size=5)

    schema = (
        pathlib.Path(__file__).parent.parent / "migrations" / "001_initial_schema.sql"
    ).read_text()
    async with pool.acquire() as conn:
        await conn.execute(schema)

    yield pool

    await pool.close()


@pytest.fixture(scope="session")
async def seed_ids(db_pool: asyncpg.Pool) -> tuple[int, int]:
    """Returns (user_id, product_kb_id) for a seeded test user and product_kb."""
    seed_settings = Settings.model_construct(
        seed_user_telegram_id=1,
        seed_user_email="seed@test.com",
        seed_product_name="SeedProduct",
        seed_product_one_liner="Test one liner",
        seed_product_description="Test description",
        seed_product_icp="Test ICP",
        seed_product_brand_voice="Test voice",
        seed_product_landing_url="https://seed.example.com",
    )
    product_kb_id = await ensure_seed_data(db_pool, seed_settings)
    user_id = await db_pool.fetchval("SELECT user_id FROM product_kb WHERE id = $1", product_kb_id)
    return user_id, product_kb_id
