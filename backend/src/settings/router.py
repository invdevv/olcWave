from fastapi import APIRouter, Depends

from auth.dependencies import get_current_admin
from config import settings
from settings.schemas import RuntimeSettings
from settings.service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


def _public_settings() -> dict:
    """Full settings for the browser, with any secrets masked out."""
    current = SettingsService.get()
    data = current.model_dump(mode="json")
    data["room_autogen_tokens"] = {}  # never expose provider tokens
    return data


@router.get("/")
async def get_settings(_admin: dict = Depends(get_current_admin)):
    return _public_settings()


@router.put("/")
async def set_setting(new: RuntimeSettings, _admin: dict = Depends(get_current_admin)):
    # room_autogen_tokens is managed elsewhere and masked in GET, so a generic
    # settings round-trip must never wipe it.
    current = SettingsService.get()
    new.room_autogen_tokens = current.room_autogen_tokens
    await SettingsService.set(new)

    return _public_settings()


@router.get("/rw_enabled")
async def get_rw_enabled(_admin: dict = Depends(get_current_admin)) -> bool:
    return settings.RW_ENABLED
