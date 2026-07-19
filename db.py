"""Postgres access layer. All month/day boundaries are evaluated in BOT_TIMEZONE."""

import datetime as dt
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import asyncpg

from config import BOT_TIMEZONE, DATABASE_URL, DEFAULT_CURRENCY

_pool: asyncpg.Pool | None = None

TZ = ZoneInfo(BOT_TIMEZONE)


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("db.connect() has not been called")
    return _pool


async def connect() -> None:
    """Open the pool and apply the schema (idempotent)."""
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    schema = Path(__file__).with_name("schema.sql").read_text()
    async with _pool.acquire() as conn:
        await conn.execute(schema)


async def close() -> None:
    if _pool is not None:
        await _pool.close()


async def ensure_user(telegram_id: int, username: str | None) -> asyncpg.Record:
    """Create the user row on first contact, then return it."""
    async with pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (telegram_id, username, currency)
            VALUES ($1, $2, $3)
            ON CONFLICT (telegram_id) DO UPDATE SET username = EXCLUDED.username
            """,
            telegram_id,
            username,
            DEFAULT_CURRENCY,
        )
        return await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1", telegram_id)


async def set_budget(telegram_id: int, amount: Decimal | None) -> None:
    async with pool().acquire() as conn:
        await conn.execute(
            "UPDATE users SET monthly_budget = $2 WHERE telegram_id = $1", telegram_id, amount
        )


async def set_currency(telegram_id: int, currency: str) -> None:
    async with pool().acquire() as conn:
        await conn.execute(
            "UPDATE users SET currency = $2 WHERE telegram_id = $1", telegram_id, currency.upper()
        )


def _to_timestamp(day: dt.date) -> dt.datetime:
    """Anchor a date to midday local time so DST shifts can't move it across days."""
    today = dt.datetime.now(TZ).date()
    if day == today:
        return dt.datetime.now(TZ)
    return dt.datetime.combine(day, dt.time(12, 0), tzinfo=TZ)


async def add_expense(
    telegram_id: int,
    amount: Decimal,
    currency: str,
    category: str,
    note: str,
    raw_text: str,
    spent_on: dt.date,
    source: str = "voice",
) -> int:
    async with pool().acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO expenses
                (telegram_id, amount, currency, category, note, raw_text, source, spent_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            telegram_id,
            amount,
            currency,
            category,
            note,
            raw_text,
            source,
            _to_timestamp(spent_on),
        )


async def month_total(telegram_id: int) -> Decimal:
    """Total spent in the current calendar month."""
    async with pool().acquire() as conn:
        value = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount), 0) FROM expenses
            WHERE telegram_id = $1
              AND date_trunc('month', spent_at AT TIME ZONE $2)
                = date_trunc('month', (now() AT TIME ZONE $2))
            """,
            telegram_id,
            BOT_TIMEZONE,
        )
        return value or Decimal(0)


async def today_total(telegram_id: int) -> Decimal:
    async with pool().acquire() as conn:
        value = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount), 0) FROM expenses
            WHERE telegram_id = $1
              AND (spent_at AT TIME ZONE $2)::date = (now() AT TIME ZONE $2)::date
            """,
            telegram_id,
            BOT_TIMEZONE,
        )
        return value or Decimal(0)


async def month_by_category(telegram_id: int) -> list[asyncpg.Record]:
    async with pool().acquire() as conn:
        return await conn.fetch(
            """
            SELECT category, SUM(amount) AS total, COUNT(*) AS n
            FROM expenses
            WHERE telegram_id = $1
              AND date_trunc('month', spent_at AT TIME ZONE $2)
                = date_trunc('month', (now() AT TIME ZONE $2))
            GROUP BY category
            ORDER BY total DESC
            """,
            telegram_id,
            BOT_TIMEZONE,
        )


async def recent(telegram_id: int, limit: int = 10) -> list[asyncpg.Record]:
    async with pool().acquire() as conn:
        return await conn.fetch(
            """
            SELECT id, amount, currency, category, note, spent_at
            FROM expenses WHERE telegram_id = $1
            ORDER BY spent_at DESC, id DESC LIMIT $2
            """,
            telegram_id,
            limit,
        )


async def delete_expense(telegram_id: int, expense_id: int) -> asyncpg.Record | None:
    """Delete one expense, scoped to its owner so IDs can't be guessed across users."""
    async with pool().acquire() as conn:
        return await conn.fetchrow(
            """
            DELETE FROM expenses WHERE id = $1 AND telegram_id = $2
            RETURNING amount, currency, category, note
            """,
            expense_id,
            telegram_id,
        )


async def delete_last(telegram_id: int) -> asyncpg.Record | None:
    async with pool().acquire() as conn:
        return await conn.fetchrow(
            """
            DELETE FROM expenses WHERE id = (
                SELECT id FROM expenses WHERE telegram_id = $1
                ORDER BY created_at DESC, id DESC LIMIT 1
            )
            RETURNING amount, currency, category, note
            """,
            telegram_id,
        )


async def all_expenses(telegram_id: int) -> list[asyncpg.Record]:
    async with pool().acquire() as conn:
        return await conn.fetch(
            """
            SELECT spent_at, amount, currency, category, note, raw_text
            FROM expenses WHERE telegram_id = $1
            ORDER BY spent_at
            """,
            telegram_id,
        )
