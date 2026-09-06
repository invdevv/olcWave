"""Durable bookkeeping for the room rotator.

The rotator's working set - which rooms exist and how old they are, which token
is dead, what each client was last told - used to live only in process memory. A
restart therefore forgot all of it, and a restart is exactly when it matters: the
standby was reaped, the pool was refilled with brand-new rooms no connected
client could learn, and every room's real birth was reset to "now", quietly
miscalibrating the guard that stops us riding a room to its provider expiry.

Everything here is best-effort. A storage failure is logged and swallowed: losing
persistence must degrade the rotator to its old in-memory behaviour, never take
the API down with it.

Values are JSON rather than pickle on purpose. The classes above this layer move
often, and a pickle written before a refactor fails to load after one - silently,
because the load is wrapped. JSON survives a renamed field, and can be read with
a query when something needs explaining.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, async_session_factory


class RotatorState(Base):
    """One JSON blob per logical bucket (`room_pool`, `slot:<name>`, ...)."""

    __tablename__ = "rotator_state"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def _log(message: str) -> None:
    print(f"[persistence] {message}", flush=True)


async def save(key: str, value: Any) -> None:
    """Upsert one bucket. Never raises."""
    try:
        async with async_session_factory() as session:
            await session.execute(
                pg_insert(RotatorState)
                .values(key=key, value=value)
                .on_conflict_do_update(
                    index_elements=[RotatorState.key],
                    set_={"value": value, "updated_at": func.now()},
                )
            )
            await session.commit()
    except Exception as exc:
        _log(f"save {key} failed: {exc}")


async def load(key: str) -> Any | None:
    """Read one bucket, or None when absent or unreadable."""
    try:
        async with async_session_factory() as session:
            row = await session.scalar(
                select(RotatorState).where(RotatorState.key == key)
            )
            return row.value if row is not None else None
    except Exception as exc:
        _log(f"load {key} failed: {exc}")
        return None
