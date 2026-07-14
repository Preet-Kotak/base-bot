import asyncpg
from typing import Optional
from config import DATABASE_URL

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        # Disable statement caching for Supabase pgbouncer compatibility
        _pool = await asyncpg.create_pool(
            url, 
            min_size=1, 
            max_size=5,
            statement_cache_size=0
        )
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bases (
                id               SERIAL PRIMARY KEY,
                district_number  INTEGER NOT NULL,
                link             TEXT NOT NULL,
                screenshot       TEXT,
                builder_name     TEXT,
                description      TEXT,
                added_at         TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS clans (
                id          SERIAL PRIMARY KEY,
                clan_name   TEXT NOT NULL,
                clan_link   TEXT NOT NULL UNIQUE,
                owner       TEXT,
                description TEXT,
                added_at    TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS timezones (
                id         SERIAL PRIMARY KEY,
                offset_str TEXT NOT NULL UNIQUE,
                label      TEXT,
                added_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS birthdays (
                id              SERIAL PRIMARY KEY,
                discord_user_id TEXT NOT NULL UNIQUE,
                birth_month     INTEGER NOT NULL,
                birth_day       INTEGER NOT NULL,
                timezone_offset TEXT NOT NULL DEFAULT '+05:30',
                added_at        TIMESTAMPTZ DEFAULT NOW()
            )
        """)
