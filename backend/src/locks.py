"""Per-user async locks.

Both the reactive self-heal (`Subscriptions.ensure_profiles_running`, triggered
on a `/sub` poll) and the proactive `RoomRotator` recreate a user's OLCRTC
containers. Serializing them per user prevents the two from racing on the same
container (double-remove / orphaned container / duplicate run).
"""

import asyncio


_user_locks: dict[str, asyncio.Lock] = {}


def get_user_lock(short_uuid: str) -> asyncio.Lock:
    lock = _user_locks.get(short_uuid)
    if lock is None:
        lock = asyncio.Lock()
        _user_locks[short_uuid] = lock
    return lock
