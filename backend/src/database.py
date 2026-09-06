from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import settings


async_engine: AsyncEngine = create_async_engine(
    settings.DB_URL,
    echo=False,
)

async_session_factory = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


class Base(DeclarativeBase):
    pass


async def create_tables(reload: bool = False) -> None:
    async with async_engine.begin() as conn:
        if reload:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight, idempotent migrations (olcWave has no Alembic).
        # create_all never ADDs columns to an existing table, so do it here.
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN IF NOT EXISTS profiles JSON")
        )