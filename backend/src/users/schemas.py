from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict

from settings.service import SettingsService


class UserSchema(BaseModel):
    short_uuid: str = Field(max_length=255)
    name: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(default = datetime.now(timezone.utc))
    expires_at: datetime = Field(default = datetime(year=1971, month=1, day=1, hour=5, tzinfo=timezone.utc))
    traffic_limit_bytes: int = Field(default_factory=lambda: SettingsService.get().default_traffic_limit)
    traffic_used_bytes: int = Field(default=0)
    # null = all profiles (legacy/unset); [] = none; [tags...] = exactly those
    profiles: list[str] | None = Field(default=None)

    model_config = ConfigDict(from_attributes=True)


class TrafficInfoSchema(BaseModel):
    short_uuid: str
    limit: int
    used: int
    remaining: int
    unlimited: bool
    exceeded: bool


class TrafficLimitUpdate(BaseModel):
    traffic_limit_bytes: int = Field(ge=0)  # pyright: ignore[reportUnannotatedClassAttribute]