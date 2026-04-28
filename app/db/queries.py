from typing import Any
import asyncpg

from app.models.product_kb import ProductKB


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
