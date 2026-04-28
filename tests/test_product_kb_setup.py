import pytest
from app.db.setup import ensure_seed_data
from app.db.queries import get_product_kb
from app.config import Settings


def _make_settings(**overrides: object) -> Settings:
    defaults = dict(
        database_url="postgresql://unused/unused",
        seed_user_telegram_id=11111,
        seed_user_email="setup@test.com",
        seed_product_name="TestProduct",
        seed_product_one_liner="One liner",
        seed_product_description="Description",
        seed_product_icp="Developers",
        seed_product_brand_voice="Professional",
        seed_product_landing_url="https://example.com",
    )
    defaults.update(overrides)
    return Settings.model_construct(**defaults)


@pytest.mark.asyncio
async def test_ensure_seed_data_returns_product_kb_id(db_pool):
    settings = _make_settings(seed_user_telegram_id=11111, seed_user_email="s1@test.com")
    product_kb_id = await ensure_seed_data(db_pool, settings)
    assert isinstance(product_kb_id, int)
    assert product_kb_id > 0


@pytest.mark.asyncio
async def test_ensure_seed_data_is_idempotent(db_pool):
    settings = _make_settings(seed_user_telegram_id=22222, seed_user_email="s2@test.com")
    id1 = await ensure_seed_data(db_pool, settings)
    id2 = await ensure_seed_data(db_pool, settings)
    assert id1 == id2


@pytest.mark.asyncio
async def test_ensure_seed_data_stores_correct_product_name(db_pool):
    settings = _make_settings(
        seed_user_telegram_id=33333,
        seed_user_email="s3@test.com",
        seed_product_name="MyStartup",
    )
    product_kb_id = await ensure_seed_data(db_pool, settings)
    row = await db_pool.fetchrow("SELECT product_name FROM product_kb WHERE id = $1", product_kb_id)
    assert row["product_name"] == "MyStartup"


@pytest.mark.asyncio
async def test_get_product_kb_returns_seeded_data(db_pool):
    settings = _make_settings(seed_user_telegram_id=44444, seed_user_email="s4@test.com")
    await ensure_seed_data(db_pool, settings)
    kb = await get_product_kb(db_pool)
    assert kb is not None
    assert kb.user_id > 0
    assert kb.product_name != ""
