import re
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


DURATION_RE = re.compile(r"^(\d+)([mhd])$")


def _parse_duration_minutes(value: str) -> int:
    match = DURATION_RE.match(value)
    if not match:
        raise ValueError("Invalid format. Use <number> + m/h/d (e.g. 5m, 1h, 7d).")

    number = int(match.group(1))
    unit = match.group(2)

    multiplier = {"m": 1, "h": 60, "d": 1440}
    return number * multiplier[unit]


def _parse_duration_seconds(value: str) -> int:
    return _parse_duration_minutes(value) * 60


class YandexAccount(BaseModel):
    """One Yandex identity used to mint Telemost rooms.

    `session_id` is the Yandex `Session_id` cookie (a secret). It is created
    manually by the operator; olcWave never auto-registers accounts.
    """

    label: str
    session_id: str = ""
    enabled: bool = True
    healthy: bool = True
    last_used_at: datetime | None = None
    cooldown_minutes: int = 120
    daily_cap: int = 8
    used_today: int = 0
    used_today_date: str = ""


class RuntimeSettings(BaseModel):
    sub_name: str = "OLCWave"
    sub_update_interval: str = "10m"
    default_traffic_limit: int = 100 * 1000**3
    traffic_collect_interval: int = 10
    sync_interval: str = "4h"
    last_sync_at: datetime | None = None
    room_autogen_tokens: dict = Field(default_factory=dict)
    # Room-rotation cadence profile: "prod" = real 4-14h holds, "test" = short
    # (minutes) so a full handoff can be watched. Read live by the rotator, so a
    # toggle takes effect on the next tick without a restart.
    rotation_mode: str = "prod"


    @field_validator("rotation_mode")
    @classmethod
    def validate_rotation_mode(cls, v: str) -> str:
        if v not in ("prod", "test"):
            raise ValueError("rotation_mode must be 'prod' or 'test'")
        return v

    @field_validator("sub_update_interval")
    @classmethod
    def validate_sub_update_interval(cls, v: str) -> str:
        if not DURATION_RE.match(v):
            raise ValueError(
                "Invalid format. Use <number> + m/h/d (e.g. 5m, 1h, 7d)."
            )

        minutes = _parse_duration_minutes(v)

        if minutes < 5:
            raise ValueError("Interval must be at least 5m.")
        if minutes > 43200:
            raise ValueError("Interval must be at most 30d.")

        return v


# --- API views (never expose Session_id secrets to the browser) ---


class YandexAccountPublic(BaseModel):
    label: str
    has_session: bool
    enabled: bool
    healthy: bool
    last_used_at: datetime | None
    cooldown_minutes: int
    daily_cap: int
    used_today: int

    @classmethod
    def of(cls, account: "YandexAccount") -> "YandexAccountPublic":
        return cls(
            label=account.label,
            has_session=bool(account.session_id),
            enabled=account.enabled,
            healthy=account.healthy,
            last_used_at=account.last_used_at,
            cooldown_minutes=account.cooldown_minutes,
            daily_cap=account.daily_cap,
            used_today=account.used_today,
        )


class YandexAccountUpsert(BaseModel):
    label: str
    session_id: str | None = None   # empty/None on update = keep existing
    enabled: bool | None = None
    cooldown_minutes: int | None = None
    daily_cap: int | None = None
