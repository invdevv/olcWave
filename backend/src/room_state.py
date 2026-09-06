"""Shared, in-memory coordination between the /sub endpoint and RoomRotator.

- ``last_fetch``: per-user epoch of the most recent successful /sub fetch. On a
  whitelist the client can only reach /sub *through* a live tunnel, so a fetch is
  proof it received whatever /sub advertised. Used twice: as the rotation ACK
  ("the client stored the NEXT room, safe to tear the old one down") and, after a
  swap, as the "client (re)joined" trigger that arms the next cycle.
- ``advertised``: per ``(profile_tag, short_uuid)`` the extra failover room id(s)
  shown in /sub as a ``##rooms`` header during a HANDOFF, while the container
  still serves the CURRENT (primary) room. They share the primary's key, so a
  dynamic-list client can add them to its in-process failover set and hop to one
  before the old room dies. Old single-room clients ignore ``##rooms``.

Everything is in-memory: a restart just means no pending handoff and a fresh ACK
clock, which the state machine tolerates (it re-arms on the next fetch).
"""

import time


class RoomState:
    last_fetch: dict[str, float] = {}
    advertised: dict[tuple[str, str], list[str]] = {}
    # Per (profile_tag, short_uuid): the set of room ids the LAST /sub actually
    # DELIVERED to the client (primary + ##rooms extras) and the epoch it went out.
    # This is the hard swap gate: the rotator tears the current room down only once
    # the client's own latest list is KNOWN to contain both the current room AND the
    # standby it must hop to. (`fetched_after` only proved "a fetch happened after we
    # advertised"; this proves WHICH rooms the client actually received.)
    delivered: dict[tuple[str, str], tuple[set[str], float]] = {}

    # Set by every mutator; the rotator loop flushes to storage when it sees it.
    # Writing from here directly would put a database round trip on the /sub
    # request path for state the rotator is the only consumer of.
    dirty: bool = False

    @staticmethod
    def note_fetch(short_uuid: str) -> None:
        RoomState.last_fetch[short_uuid] = time.time()
        RoomState.dirty = True

    @staticmethod
    def note_delivered(tag: str, short_uuid: str, rooms: set[str]) -> None:
        RoomState.delivered[(tag, short_uuid)] = (set(rooms), time.time())
        RoomState.dirty = True

    @staticmethod
    def snapshot() -> dict:
        """JSON-able view. Tuple keys become explicit records so a reader can
        tell what they are without knowing the key encoding."""
        return {
            "last_fetch": dict(RoomState.last_fetch),
            "delivered": [
                {"tag": tag, "uuid": uuid, "rooms": sorted(rooms), "at": at}
                for (tag, uuid), (rooms, at) in RoomState.delivered.items()
            ],
            "advertised": [
                {"tag": tag, "uuid": uuid, "rooms": list(rooms)}
                for (tag, uuid), rooms in RoomState.advertised.items()
            ],
        }

    @staticmethod
    def restore(data: dict | None) -> None:
        """Load a snapshot, ignoring anything malformed. A partially restored
        state is still better than none: every field only ever makes the swap
        gate MORE permissive by being present, and the gate has other checks."""
        if not isinstance(data, dict):
            return
        raw_fetch = data.get("last_fetch")
        if isinstance(raw_fetch, dict):
            RoomState.last_fetch = {
                str(k): float(v)
                for k, v in raw_fetch.items()
                if isinstance(v, (int, float))
            }
        for record in data.get("delivered") or []:
            try:
                RoomState.delivered[(record["tag"], record["uuid"])] = (
                    set(record["rooms"]),
                    float(record["at"]),
                )
            except Exception:
                continue
        for record in data.get("advertised") or []:
            try:
                RoomState.advertised[(record["tag"], record["uuid"])] = list(
                    record["rooms"]
                )
            except Exception:
                continue

    @staticmethod
    def delivered_rooms(tag: str, short_uuid: str) -> set[str]:
        entry = RoomState.delivered.get((tag, short_uuid))
        return set(entry[0]) if entry else set()

    @staticmethod
    def fetched_after(short_uuid: str, ts: float) -> bool:
        return RoomState.last_fetch.get(short_uuid, 0.0) > ts

    @staticmethod
    def set_advertised(tag: str, short_uuid: str, rooms: list[str]) -> None:
        RoomState.advertised[(tag, short_uuid)] = rooms
        RoomState.dirty = True

    @staticmethod
    def get_advertised(tag: str, short_uuid: str) -> list[str] | None:
        return RoomState.advertised.get((tag, short_uuid))

    @staticmethod
    def clear_advertised(tag: str, short_uuid: str) -> None:
        RoomState.advertised.pop((tag, short_uuid), None)
        RoomState.dirty = True
