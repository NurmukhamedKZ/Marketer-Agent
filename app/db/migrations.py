import asyncio
import pathlib
import asyncpg
from app.config import get_settings

MIGRATIONS_DIR = pathlib.Path(__file__).parent.parent.parent / "migrations"


async def run_migrations() -> None:
    settings = get_settings()
    conn = await asyncpg.connect(settings.database_url)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    applied = {
        r["version"]
        for r in await conn.fetch("SELECT version FROM schema_migrations")
    }

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    for path in sql_files:
        version = path.name
        if version in applied:
            print(f"  skip  {version}")
            continue

        print(f"  apply {version} ... ", end="", flush=True)
        sql = path.read_text()
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_migrations (version) VALUES ($1)", version
            )
        print("done")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
