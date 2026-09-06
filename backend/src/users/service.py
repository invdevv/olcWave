import asyncio
from datetime import datetime, timezone

from config import settings
from settings.service import SettingsService
from database import async_session_factory
from users.db import UserDB
from users.schemas import UserSchema, TrafficInfoSchema

class Users:
    @staticmethod
    async def add(user: UserSchema):
        async with async_session_factory() as db:
            return await UserDB.add(db, user)

    @staticmethod
    async def exists(short_uuid: str) -> bool:
        async with async_session_factory() as db:
            return await UserDB.exists(db, short_uuid)

    @staticmethod
    async def get(short_uuid: str) -> UserSchema:
        async with async_session_factory() as db:
            user = await UserDB.get(db, short_uuid)
        return user

    @staticmethod
    async def update(user: UserSchema):
        async with async_session_factory() as db:
            _ = await UserDB.update(db, user)

    @staticmethod
    async def delete(short_uuid: str):
        async with async_session_factory() as db:
            _ = await UserDB.delete(db, short_uuid)

    @staticmethod
    async def get_all() -> list[UserSchema]:
        async with async_session_factory() as db:
            users: list[UserSchema] = await UserDB.get_all(db)
        return users

    @staticmethod
    async def get_traffic(short_uuid: str) -> TrafficInfoSchema:
        user = await Users.get(short_uuid)
        unlimited = user.traffic_limit_bytes == 0
        remaining = 0 if unlimited else max(0, user.traffic_limit_bytes - user.traffic_used_bytes)
        exceeded = (not unlimited) and user.traffic_used_bytes >= user.traffic_limit_bytes
        return TrafficInfoSchema(
            short_uuid=short_uuid,
            limit=user.traffic_limit_bytes,
            used=user.traffic_used_bytes,
            remaining=remaining,
            unlimited=unlimited,
            exceeded=exceeded,
        )

    @staticmethod
    async def set_traffic_limit(short_uuid: str, limit: int):
        async with async_session_factory() as db:
            await UserDB.set_traffic_limit(db, short_uuid, limit)

    @staticmethod
    async def reset_traffic(short_uuid: str):
        async with async_session_factory() as db:
            await UserDB.reset_traffic(db, short_uuid)

    @staticmethod
    async def add_traffic_used(short_uuid: str, delta: int):
        if delta <= 0:
            return
        async with async_session_factory() as db:
            await UserDB.update_traffic_used(db, short_uuid, delta)

    @staticmethod
    async def sync_with_remnawave():
        if not settings.RW_ENABLED:
            raise RuntimeError("Remnawave is not enabled")

        from rw.sdk import getAllUsers, isUserInSquad

        rw_users = await getAllUsers()
        db_users = await Users.get_all()

        rw_map = {
            u.short_uuid: u
            for u in rw_users.users
            if isUserInSquad(u)
        }

        db_map = {u.short_uuid: u for u in db_users}

        created = 0
        updated = 0
        deleted = 0

        for short_uuid, rw_user in rw_map.items():
            if short_uuid not in db_map:
                await Users.add(
                    UserSchema(
                        short_uuid=rw_user.short_uuid,
                        name=rw_user.username,
                        expires_at=rw_user.expire_at,
                    )
                )
                created += 1
            else:
                db_user = db_map[short_uuid]

                if (
                    db_user.expires_at != rw_user.expire_at
                    or db_user.name != rw_user.username
                ):
                    updated_user = db_user.model_copy(
                        update={
                            "name": rw_user.username,
                            "expires_at": rw_user.expire_at,
                        }
                    )

                    await Users.update(updated_user)

                    updated += 1

        for short_uuid in db_map:
            if short_uuid not in rw_map:
                await Users.delete(short_uuid)
                deleted += 1

        await SettingsService.update_last_sync(datetime.now(timezone.utc))

        return {
            "created": created,
            "updated": updated,
            "deleted": deleted,
        }
