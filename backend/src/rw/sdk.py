from uuid import UUID

from remnawave.models.users import GetAllUsersResponseDto, UserResponseDto
from remnawave.models.users import GetUserByShortUuidResponseDto
from remnawave.models.subscription import GetSubscriptionInfoResponseDto
from remnawave import RemnawaveSDK
from remnawave.exceptions.general import NotFoundError
from remnawave.models import (
    SubscriptionInfoResponseDto,
    SubscriptionSettingsResponseDto
)

from config import settings


def make_uuid_optional(model) -> None:
    field = model.model_fields.get("uuid")

    if field is None:
        return

    field.annotation = UUID | None
    field.default = None

    model.model_rebuild(force=True)


def patch_remnawave_users() -> None:
    """Patch the Remnawave SDK models to make the `uuid` field optional in certain user-related response DTOs."""
    make_uuid_optional(UserResponseDto)
    make_uuid_optional(GetUserByShortUuidResponseDto)
    GetAllUsersResponseDto.model_rebuild(force=True)


patch_remnawave_users()


_remnawave: RemnawaveSDK | None = None


def _get_sdk() -> RemnawaveSDK:
    global _remnawave
    if _remnawave is None:
        _remnawave = RemnawaveSDK(
            base_url=settings.RW_API_URL,
            token=settings.RW_API_TOKEN,
            caddy_token=settings.RW_CADDY_TOKEN or None,
        )
    return _remnawave


def _ensure_enabled():
    if not settings.RW_ENABLED:
        raise RuntimeError("Remnawave is not enabled")


async def getAllUsers() -> GetAllUsersResponseDto:
    _ensure_enabled()
    sdk = _get_sdk()
    PAGE_SIZE = 100

    start = 0
    users: list[UserResponseDto] = []

    while True:
        response = await sdk.users.get_all_users(
            start=start,
            size=PAGE_SIZE,
        )

        users.extend(response.users)

        if len(response.users) < PAGE_SIZE or len(users) >= response.total:
            break

        start += len(response.users)

    return GetAllUsersResponseDto(
        users=users,
        total=len(users),
    )

def isUserInSquad(user: UserResponseDto) -> bool:
    if not settings.RW_SQUAD_NAME:
        return True

    return any(
        settings.RW_SQUAD_NAME == squad.name or settings.RW_SQUAD_NAME == str(squad.uuid)
        for squad in user.active_internal_squads
    )

async def isUserValid(short_uuid: str) -> SubscriptionInfoResponseDto | None:
    _ensure_enabled()
    sdk = _get_sdk()

    try:
        sub: GetSubscriptionInfoResponseDto = await sdk.subscription.get_subscription_info_by_short_uuid(short_uuid)  # pyright: ignore[reportAssignmentType]

        if not sub.is_found:
            return None

        if settings.RW_SQUAD_NAME:
            user: GetUserByShortUuidResponseDto = await sdk.users.get_user_by_short_uuid(short_uuid)  # pyright: ignore[reportAssignmentType]

            if not isUserInSquad(user):
                return None
       
        return sub

    except NotFoundError:
        return None


async def getSubscriptionSettings():
    _ensure_enabled()
    sdk = _get_sdk()

    sub: SubscriptionSettingsResponseDto = await sdk.subscriptions_settings.get_settings()  # pyright: ignore[reportAssignmentType, reportUnknownVariableType]

    return sub
