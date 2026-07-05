from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, future=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "sqlite":
            await _upgrade_sqlite_schema(conn)


async def _upgrade_sqlite_schema(conn) -> None:
    await _add_missing_columns(
        conn,
        "user_state",
        {
            "onboarding_status": "VARCHAR(20) DEFAULT 'not_started'",
            "onboarding_skill_id": "VARCHAR(120)",
        },
    )
    await _add_missing_columns(
        conn,
        "task_progress",
        {
            "attempt_count": "INTEGER DEFAULT 0",
            "review_summary": "TEXT DEFAULT ''",
            "skill_evidence": "TEXT DEFAULT ''",
            "completed_at": "DATETIME",
        },
    )


async def _add_missing_columns(conn, table_name: str, columns: dict[str, str]) -> None:
    existing = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    existing_names = {row[1] for row in existing.fetchall()}
    for column_name, definition in columns.items():
        if column_name not in existing_names:
            await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))


async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
