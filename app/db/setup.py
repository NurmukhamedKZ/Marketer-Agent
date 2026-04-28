import asyncpg
from app.config import Settings


async def ensure_seed_data(pool: asyncpg.Pool, settings: Settings) -> int:
    """Create seed user and product_kb if they don't exist. Returns product_kb_id."""
    async with pool.acquire() as conn:
        user_id: int = await conn.fetchval(
            """
            INSERT INTO users (telegram_id, email)
            VALUES ($1, $2)
            ON CONFLICT (telegram_id) DO UPDATE SET telegram_id = EXCLUDED.telegram_id
            RETURNING id
            """,
            settings.seed_user_telegram_id,
            settings.seed_user_email or None,
        )

        product_kb_id: int | None = await conn.fetchval(
            "SELECT id FROM product_kb WHERE user_id = $1 LIMIT 1",
            user_id,
        )
        if product_kb_id is None:
            product_kb_id = await conn.fetchval(
                """
                INSERT INTO product_kb
                    (user_id, product_name, one_liner, description, icp, brand_voice, landing_url)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                user_id,
                settings.seed_product_name,
                settings.seed_product_one_liner,
                settings.seed_product_description,
                settings.seed_product_icp,
                settings.seed_product_brand_voice,
                settings.seed_product_landing_url,
            )

    return product_kb_id
