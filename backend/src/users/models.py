from sqlalchemy import BigInteger, DateTime, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column

from datetime import datetime
from typing import Annotated

from database import Base

UTC_NOW = Annotated[datetime, mapped_column(DateTime(timezone=True), server_default=text("now()"))]

class User(Base):
    __tablename__ = "users"                                      # pyright: ignore[reportUnannotatedClassAttribute]

    id: Mapped[int] = mapped_column(primary_key=True)
    short_uuid: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[UTC_NOW]  # pyright: ignore[reportUninitializedInstanceVariable]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # pyright: ignore[reportUninitializedInstanceVariable]
    traffic_limit_bytes: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    traffic_used_bytes: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    # null = all profiles (legacy/unset); [] = none; [tags...] = exactly those
    profiles: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)