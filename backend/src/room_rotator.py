"""Per-container Telemost room rotation with an ACK-gated handoff.

Activation is implicit and per-profile, by how many Session_id tokens the
profile carries (see ``Subscriptions.profile_tokens``):

- 0 / 1 token  -> no rotation. A 1-token profile just autogenerates a room
  reactively on the next /sub poll, exactly like before.
- >= 2 tokens  -> this rotator runs a per-container state machine that keeps a
  live room continuously available and hands the client from the old room onto
  a freshly minted one WITHOUT waiting for it to hit a dead room.

Why a handoff and not a hard swap: on a whitelist the client can only reach
/sub THROUGH the live tunnel, so the next room must be delivered (advertised)
while the current room is still up, and confirmed received (ACK = a /sub fetch)
before the current room is torn down. olcbox uses only the single ACTIVE room in
a subscription, so "next" is delivered by flipping the advertised room to it
(``RoomState.advertised``), never as a second entry.

State per container ``olcwave-<tag>-<uuid>``:
  HOLD    - serving current_room; /sub advertises it; idle until a client fetches
            /sub (proxy for "joined"), then ARM with a random 1-14h hold time.
  ARMED   - wait until ``deadline - LEAD``; then mint next_room and advertise it.
  HANDOFF - /sub advertises next_room while the container still serves current;
            wait for ACK (+ deadline + next still alive), then SWAP the container
            onto next_room. current dies, the client auto-reconnects onto next.

One container per (tag, uuid) by name, so no server-side overlap is possible:
the swap costs the client a short reconnect. Telemost has no close API; abandoned
rooms just expire (~24h). Registered as a background task in main.py.
"""

import asyncio
import json
import re
import random
import time

import yaml

from profiles.service import Profiles
from profiles.roomGenerator import RoomGenerator
from subscriptions.service import Subscriptions
from olcrtc.service import Containers
from olcrtc.sdk import OlcRTC
from locks import get_user_lock
from room_state import RoomState
import persistence


MIN_TOKENS_FOR_ROTATION = 2

# --- Rotation cadence: two profiles, chosen LIVE from RuntimeSettings.rotation_mode
# (the panel "prod"/"test" toggle) so flipping it takes effect on the next tick with
# NO restart. "prod" = the real 4-14h holds; "test" = short (minutes) so a full
# handoff can be watched end-to-end. Only the cadence knobs differ here; the
# physical-expiry knobs below (tied to Telemost's ~24h instant-room life) are the
# same in both modes. ---
_CADENCE = {
    "prod": {"hold_min": 4 * 3600, "hold_max": 14 * 3600, "tick": 45},
    "test": {"hold_min": 3 * 60,   "hold_max": 8 * 60,    "tick": 10},
}
# --- end timings ---
ROOM_LIFETIME_SECONDS = 24 * 3600    # ~Telemost instant-room expiry
SWAP_SAFETY_SECONDS = 60 * 60        # never schedule a swap later than this before expiry
BROKEN_BUFFER_SECONDS = 30 * 60      # give up waiting for ACK this long before expiry
TOKEN_REFRESH_INTERVAL = 6 * 3600    # how often to pull a fresh Session_id from the vault for managed tokens
STANDBY_SUFFIX = "-nx"               # standby container name suffix (4-part -> invisible to discovery)


class RoomRotator:
    # container name -> control state dict
    _state: dict[str, dict] = {}
    # last time managed (vault-backed) tokens were refreshed from the vault
    _last_token_refresh: float = 0.0
    # serialized copy of what storage already holds, so a tick only writes on a
    # real change instead of once every cadence forever
    _persisted_slots: str | None = None
    _persisted_pool: str | None = None

    # A deadline that lapsed while we were down must not fire the instant we come
    # back: the client is still re-establishing, and a swap needs it settled on
    # the current room. Push such a deadline out by this much instead.
    RESUME_GRACE_SECONDS = 120

    # How many consecutive "the provider says this room does not exist" verdicts
    # it takes to retire a room. Retiring the primary is the one rotation that is
    # not gated on the client having a live room to move to, so a single bad probe
    # must not be able to trigger it. Consecutive: any other answer clears it.
    DEAD_STRIKES_REQUIRED = 3
    _dead_strikes: dict[str, int] = {}

    # Fields of a slot's state that survive a restart. `standby_config` is
    # deliberately absent - it embeds the failover group's crypto key, and it is
    # rebuilt by the next _ensure_standby anyway.
    _PERSISTED_SLOT_FIELDS = (
        "state",
        "hold_entered_at",
        "current_created",
        "armed",
        "swap_deadline",
        "standby",
        "standby_room",
        "standby_advertised_at",
        "vacated",
    )

    @staticmethod
    def _log(message: str) -> None:
        print(f"[olcwave-rotator] {message}", flush=True)

    # ------------------------------------------------------------------ resume

    @staticmethod
    def _slot_snapshot() -> dict:
        return {
            name: {f: st.get(f) for f in RoomRotator._PERSISTED_SLOT_FIELDS}
            for name, st in RoomRotator._state.items()
        }

    @staticmethod
    async def restore() -> None:
        """Come back up where we left off.

        Two sources, in order of authority. Docker is the truth for what is
        RUNNING - which rooms are served and by which container - so that is read
        first and never overridden. Storage supplies only what cannot be observed:
        how old each room really is, what each client was last told, and where the
        rotation cycle had got to.
        """
        pool_restored = 0
        try:
            tokens: list[str] = []
            for profile in await Profiles.get_all():
                tokens.extend(
                    Subscriptions.profile_tokens(RoomRotator._parse(profile.profile))
                )
            pool_restored = RoomGenerator.restore(
                await persistence.load("room_pool"), tokens
            )
        except Exception as exc:
            RoomRotator._log(f"pool restore skipped: {exc}")

        RoomState.restore(await persistence.load("room_state"))

        now = RoomRotator._now()
        slots = await persistence.load("slots")
        deferred = 0
        if isinstance(slots, dict):
            for name, saved in slots.items():
                if not isinstance(saved, dict):
                    continue
                st = {f: saved.get(f) for f in RoomRotator._PERSISTED_SLOT_FIELDS}
                st["standby_config"] = None
                deadline = st.get("swap_deadline")
                if isinstance(deadline, (int, float)) and deadline < now:
                    st["swap_deadline"] = now + RoomRotator.RESUME_GRACE_SECONDS
                    deferred += 1
                RoomRotator._state[name] = st

        RoomRotator._persisted_slots = json.dumps(
            RoomRotator._slot_snapshot(), sort_keys=True, default=str
        )
        RoomRotator._log(
            f"resumed: {len(RoomRotator._state)} slot(s), {pool_restored} pooled room(s)"
            + (f", {deferred} lapsed deadline(s) deferred" if deferred else "")
        )

    @staticmethod
    async def _adopt_running_rooms(containers, targets: dict) -> None:
        """Teach the pool about rooms that are already being served.

        A running container outlives us, so after a restart the room a client is
        CONNECTED to may be absent from the pool. `room_created_at` then returns
        None, `_set_hold` falls back to "born now", and the expiry guard starts
        counting from the wrong birth - which is how a room gets ridden to its
        real provider expiry with a client still on it.

        Age is unknown for a room we only learn about from a container, so it is
        adopted as "born now". That is the same assumption the old code made, but
        it now applies only to rooms storage never knew about, instead of to
        every room after every restart.
        """
        for container in containers:
            target = targets.get(container.config_tag)
            if not target:
                continue
            try:
                room_id = await RoomRotator._current_room_id(container.name)
                if not room_id or RoomGenerator.room_created_at(room_id):
                    continue
                tokens = target[2]
                if tokens:
                    RoomGenerator.adopt_room(tokens[0], room_id)
            except Exception:
                continue

    @staticmethod
    async def _persist() -> None:
        """Write through whatever actually changed this tick."""
        slots = json.dumps(RoomRotator._slot_snapshot(), sort_keys=True, default=str)
        if slots != RoomRotator._persisted_slots:
            await persistence.save("slots", json.loads(slots))
            RoomRotator._persisted_slots = slots

        pool = json.dumps(RoomGenerator.snapshot(), sort_keys=True, default=str)
        if pool != RoomRotator._persisted_pool:
            await persistence.save("room_pool", json.loads(pool))
            RoomRotator._persisted_pool = pool

        if RoomState.dirty:
            await persistence.save("room_state", RoomState.snapshot())
            RoomState.dirty = False

    @staticmethod
    def _now() -> float:
        return time.time()

    @staticmethod
    def _cadence() -> dict:
        """Live rotation-cadence profile from the panel toggle
        (RuntimeSettings.rotation_mode). Falls back to prod if settings are not
        loaded yet or the value is unknown, so the rotator is never left without
        timings."""
        try:
            from settings.service import SettingsService
            mode = getattr(SettingsService.get(), "rotation_mode", "prod")
        except Exception:
            mode = "prod"
        return _CADENCE.get(mode, _CADENCE["prod"])

    @staticmethod
    def _parse(profile_yaml: str) -> dict:
        try:
            return yaml.safe_load(profile_yaml) or {}
        except Exception:
            return {}

    @staticmethod
    async def _current_room_id(name: str) -> str | None:
        try:
            cfg = await Containers.get_config(name)
            data = yaml.safe_load(cfg.config)
            return (data.get("room") or {}).get("id")
        except Exception:
            return None

    @staticmethod
    async def _current_key(name: str) -> str | None:
        """The container's crypto key = the failover group's shared key."""
        try:
            cfg = await Containers.get_config(name)
            data = yaml.safe_load(cfg.config)
            return (data.get("crypto") or {}).get("key")
        except Exception:
            return None

    @staticmethod
    async def _primary_is_dead(name: str, provider: str, room_id: str | None) -> bool:
        """Has the primary room definitively gone, confirmed more than once?

        This gates the ONE rotation path that is not held back by "does the client
        have somewhere to go" - so a wrong answer here retires a live room out from
        under a connected client, which on a whitelist it cannot recover from: it
        needs the tunnel to fetch the room list that would tell it where to go.

        The old test collapsed every failure into "dead": `except: return False`
        meant a timeout, a Yandex hiccup or a rate-limit was indistinguishable from
        a room that had genuinely expired. Now only an explicit "no such meeting"
        counts, and only after DEAD_STRIKES_REQUIRED of them in a row.
        """
        if not room_id:
            return False
        verdict = await RoomGenerator.room_alive(provider, room_id)
        if verdict is None:
            # Could not verify. Unknown is not dead - leave the room alone. If it
            # really has gone, the client's own liveness moves it to the standby,
            # and the near-expiry guard is still there as a backstop.
            RoomRotator._dead_strikes.pop(name, None)
            return False
        if verdict:
            RoomRotator._dead_strikes.pop(name, None)
            return False

        strikes = RoomRotator._dead_strikes.get(name, 0) + 1
        RoomRotator._dead_strikes[name] = strikes
        if strikes < RoomRotator.DEAD_STRIKES_REQUIRED:
            RoomRotator._log(
                f"{name}: room {room_id} reported gone "
                f"({strikes}/{RoomRotator.DEAD_STRIKES_REQUIRED}) - confirming before acting"
            )
            return False
        RoomRotator._log(
            f"{name}: room {room_id} confirmed gone after "
            f"{strikes} checks in a row"
        )
        RoomRotator._dead_strikes.pop(name, None)
        return True

    @staticmethod
    async def _mint(
        provider: str, tokens: list[str], exclude: set[str] | None = None
    ) -> str | None:
        # Resilient mint lives in RoomGenerator.mint_room: it rolls a random
        # active token, tries .ru then .com, drops a token that fails both realms
        # from the active pool (re-rolling the rest), never returns a room in
        # `exclude` (e.g. the current room), and returns None only when every token
        # is dead. On None we DO NOT swap - the caller keeps the current live room.
        room_id = await RoomGenerator.mint_room(provider, tokens, exclude=exclude)
        if room_id is None:
            RoomRotator._log("no live token to mint (all dead) - will retry")
        return room_id

    @staticmethod
    async def _serve(tag: str, short_uuid: str, config: str) -> None:
        name = f"olcwave-{tag}-{short_uuid}"
        async with get_user_lock(short_uuid):
            try:
                await Containers.remove(name)
            except Exception:
                pass
            await Containers.run(config, tag, short_uuid)

    @staticmethod
    def _pick_hold(created: float) -> float:
        """Random 4-14h hold, capped so the swap happens before the room's ~24h
        natural expiry (never ride a room to death mid-hold)."""
        now = RoomRotator._now()
        cad = RoomRotator._cadence()
        hold = random.uniform(cad["hold_min"], cad["hold_max"])
        remaining = ROOM_LIFETIME_SECONDS - (now - created)
        return min(hold, max(remaining - SWAP_SAFETY_SECONDS, 60))

    @staticmethod
    def _set_hold(
        name: str,
        created: float | None = None,
        armed: bool = False,
        vacated: str | None = None,
    ) -> None:
        """Enter HOLD on the current (primary) room. The rotation cycle does NOT
        start until the client is seen: `armed` stays False on first bring-up (we
        wait for someone to actually join before picking a swap time or spawning a
        standby); it is True right after a rotation, where the client is already
        present (it just hopped onto this room). `vacated` = the room we just tore
        down: it is excluded from the NEXT standby so we never resurrect the room the
        client may still be reconnecting to."""
        now = RoomRotator._now()
        created = created if created is not None else now
        st = {
            "state": "HOLD",
            "hold_entered_at": now,
            "current_created": created,   # real birth of the primary room (pool age)
            "armed": armed,
            "swap_deadline": None,
            "standby": None,
            "standby_room": None,
            "standby_config": None,
            "standby_advertised_at": None,
            "vacated": vacated,           # just-killed room, kept out of the next standby
        }
        if armed:
            hold = RoomRotator._pick_hold(created)
            st["swap_deadline"] = now + hold
            RoomRotator._log(f"{name}: rotated in, armed, swap in ~{int(hold / 60)}m")
        RoomRotator._state[name] = st

    @staticmethod
    async def _reset_to_fresh(
        profile, provider, tokens, tag, short_uuid, reason: str
    ) -> None:
        """Mint a brand-new room, serve it, drop back to HOLD (RECOVER / BROKEN)."""
        name = f"olcwave-{tag}-{short_uuid}"
        room_id = await RoomRotator._mint(provider, tokens)
        if room_id is None:
            RoomRotator._log(f"{name}: {reason}, but no working token - will retry")
            return
        try:
            config = await Subscriptions.profile_to_config(
                profile.profile, force_room_id=room_id
            )
        except Exception as exc:
            RoomRotator._log(f"{name}: failed to build fresh config: {exc}")
            return
        await RoomRotator._serve(tag, short_uuid, config)
        RoomState.clear_advertised(tag, short_uuid)
        RoomRotator._set_hold(name, RoomGenerator.room_created_at(room_id))
        RoomRotator._log(f"{name}: {reason} -> fresh room {room_id} (HOLD)")

    @staticmethod
    def _standby_name(tag: str, short_uuid: str) -> str:
        # 4-part name -> invisible to Containers.all()/get_launched_tags/panel, so
        # neither /sub nor the rotator loop treat the standby as its own slot.
        return f"olcwave-{tag}-{short_uuid}{STANDBY_SUFFIX}"

    @staticmethod
    async def _container_exists(name: str) -> bool:
        try:
            await OlcRTC.get(name)
            return True
        except Exception:
            return False

    @staticmethod
    async def _ensure_standby(
        profile, provider, tokens, tag, short_uuid, st: dict, current_room: str
    ) -> None:
        """Keep a warm standby srv running on a DISTINCT next room at all times, so
        the client always has a live failover target (advertised via ##rooms) and a
        swap is instant. (Re)spawns it only when it is missing; a running-but-ICE-
        flapping standby is left alone (it reconnects on its own)."""
        name = f"olcwave-{tag}-{short_uuid}"
        sb = st.get("standby")
        if sb and await RoomRotator._container_exists(sb):
            return

        group_key = await RoomRotator._current_key(name)
        if not group_key:
            return
        exclude = {current_room}
        if st.get("standby_room"):
            exclude.add(st["standby_room"])   # don't re-pick the standby room that just died
        if st.get("vacated"):
            # Never resurrect the room we just tore down: the client may still be
            # reconnecting to it and would re-glue to it instead of moving on.
            exclude.add(st["vacated"])
        next_room = await RoomRotator._mint(provider, tokens, exclude=exclude)
        if next_room is None:
            return  # no distinct live room right now (pool exhausted / tokens dead) - retry later
        try:
            cfg = await Subscriptions.profile_to_config(
                profile.profile, force_room_id=next_room, force_key=group_key
            )
        except Exception as exc:
            RoomRotator._log(f"{name}: failed to build standby config: {exc}")
            return
        sb_name = RoomRotator._standby_name(tag, short_uuid)
        try:
            await Containers.run(cfg, tag, short_uuid, name=sb_name)
        except Exception as exc:
            RoomRotator._log(f"{name}: failed to start standby: {exc}")
            return
        st["standby"] = sb_name
        st["standby_room"] = next_room
        st["standby_config"] = cfg
        st["standby_advertised_at"] = RoomRotator._now()
        # Advertise the standby room as a ##rooms failover extra (shares the group
        # key). Old single-room clients ignore it; dynamic-list clients keep it warm.
        RoomState.set_advertised(tag, short_uuid, [next_room])
        RoomRotator._log(f"{name}: warm standby up on {next_room} (##rooms)")

    @staticmethod
    async def _drop_standby(st: dict) -> None:
        sb = st.pop("standby", None)
        st.pop("standby_room", None)
        st.pop("standby_config", None)
        st.pop("standby_advertised_at", None)
        if sb:
            try:
                await Containers.remove(sb)
            except Exception:
                pass

    @staticmethod
    async def _client_attached(name: str) -> bool:
        """True if a tunnel client is CURRENTLY connected to this srv.

        The srv logs "Current peers count: N" on every peer open and close, so the
        newest such line is the live count.

        This is deliberately NOT the same as "the client fetched /sub". A fetch
        happens moments BEFORE the client dials the room, so treating it as proof
        of presence let a swap retire the very room the client was about to join:
        seen live on 2026-08-28, fetch at 15:54:03, swap at 15:54:07, client dialled
        the now-dead room at 15:54:08 and never got through the handshake.
        """
        try:
            raw = (await Containers.logs(name, tail=1000)).logs
        except Exception:
            return False
        last = None
        for line in raw.splitlines():
            if "current peers count:" in line.lower():
                last = line
        if last is None:
            return False
        found = re.search(r"current peers count:\s*(\d+)", last, re.IGNORECASE)
        return bool(found) and int(found.group(1)) > 0

    @staticmethod
    async def _srv_connected(name: str) -> bool:
        """True if this srv is CURRENTLY in the room (last ICE state == connected).
        The srv log flaps connected/disconnected, so only the latest state counts."""
        try:
            raw = (await Containers.logs(name, tail=200)).logs
        except Exception:
            return False
        last = None
        for line in raw.splitlines():
            if "connection state" in line.lower():
                last = line
        if last is None:
            return False
        low = last.lower()
        if "disconnect" in low:      # "disconnected" contains "connected" - check first
            return False
        return "connected" in low

    @staticmethod
    async def _rotate(
        profile, provider, tokens, tag, short_uuid, st: dict, reason: str
    ) -> None:
        """Move the slot onto its warm standby: kill the primary (the client hops to
        the standby that is already IN its room), rename the standby to the canonical
        name, then immediately establish the NEXT warm standby. If there is no warm
        standby in the room (it never came up / also died), recover onto a fresh room
        the plain way (accepts a small gap) instead."""
        name = f"olcwave-{tag}-{short_uuid}"
        # The room we are about to tear down. Kept out of the NEXT standby so the
        # just-killed room is not resurrected while the client may still be leaving it.
        old_room = await RoomRotator._current_room_id(name)
        sb = st.get("standby")
        sb_room = st.get("standby_room")
        sb_cfg = st.get("standby_config")

        if sb and sb_room and await RoomRotator._srv_connected(sb):
            async with get_user_lock(short_uuid):
                try:
                    # GRACEFUL stop (SIGTERM) first: the old srv catches it and sends
                    # the client a "control closed by peer" close on its way out, so
                    # the client fails over to the warm standby INSTANTLY instead of
                    # hammering the dead room for the whole liveness-fallback window.
                    # (A hard kill would skip that signal.) Then remove + promote.
                    await Containers.stop(name)        # SIGTERM -> srv tells the client it is leaving
                    await Containers.remove(name)      # remove the stopped old primary
                    await Containers.rename(sb, name)  # promote standby -> canonical primary
                except Exception as exc:
                    RoomRotator._log(f"{name}: promote failed: {exc}")
                    try:
                        await Containers.remove(sb)
                    except Exception:
                        pass
                    if sb_cfg:
                        await Containers.run(sb_cfg, tag, short_uuid)  # last resort: serve sb room fresh
            RoomState.clear_advertised(tag, short_uuid)
            # The client just hopped onto the promoted room -> it's present, so arm
            # immediately (start the next swap timer + warm standby now). Exclude the
            # room we just killed (old_room) from that next standby.
            RoomRotator._set_hold(
                name, RoomGenerator.room_created_at(sb_room), armed=True, vacated=old_room
            )
            RoomRotator._log(f"{name}: rotated -> {sb_room} ({reason}, warm standby promoted)")
        else:
            # No warm standby to promote -> recover onto a fresh room (accepts a gap).
            # Left un-armed: the client's tunnel dropped, so wait for it to reconnect
            # (fetch /sub) before starting the cycle again.
            await RoomRotator._drop_standby(st)
            await RoomRotator._reset_to_fresh(
                profile, provider, tokens, tag, short_uuid, reason
            )

        # Re-establish the warm standby immediately (only when armed) so the
        # 2-container invariant holds right after a successful rotation.
        new_current = await RoomRotator._current_room_id(name)
        st2 = RoomRotator._state.get(name)
        if new_current is not None and st2 is not None and st2.get("armed"):
            await RoomRotator._ensure_standby(
                profile, provider, tokens, tag, short_uuid, st2, new_current
            )

    @staticmethod
    async def _tick(profile, provider, tokens, container) -> None:
        tag = container.config_tag
        short_uuid = container.short_uuid
        name = container.name
        now = RoomRotator._now()

        current_room = await RoomRotator._current_room_id(name)
        if current_room is None:
            # Transient docker read error - don't act on missing info.
            return

        st = RoomRotator._state.get(name)
        if st is None:
            RoomRotator._set_hold(name, RoomGenerator.room_created_at(current_room))
            st = RoomRotator._state[name]

        # 1) Primary health. Only once the room is CONFIRMED gone - see
        #    _primary_is_dead - rotate onto the warm standby right away (or
        #    recover if there is no warm standby in the room).
        if await RoomRotator._primary_is_dead(name, provider, current_room):
            await RoomRotator._rotate(
                profile, provider, tokens, tag, short_uuid, st, "primary died"
            )
            return

        # Gate: the rotation cycle (pick a swap time, spawn a standby) does NOT start
        # until someone actually joins - the client fetching /sub, which on a
        # whitelist only works through the live tunnel, so a fetch == it's connected.
        if not st.get("armed"):
            if RoomState.fetched_after(short_uuid, st["hold_entered_at"]):
                st["armed"] = True
                hold = RoomRotator._pick_hold(st["current_created"])
                st["swap_deadline"] = RoomRotator._now() + hold
                RoomRotator._log(
                    f"{name}: client seen -> armed, swap in ~{int(hold / 60)}m"
                )
            else:
                return  # nobody joined yet - keep the single room waiting

        # 2) Keep a warm standby on a DISTINCT room at all times (persistent
        #    make-before-break: the client always has a live ##rooms fallback that
        #    is already IN its room, so a swap is instant and an unexpected primary
        #    death is caught with no warmup).
        await RoomRotator._ensure_standby(
            profile, provider, tokens, tag, short_uuid, st, current_room
        )

        # 3) Scheduled rotation once the random hold is up, the standby is actually
        #    in its room, and the client already holds the standby room (ACK - on a
        #    whitelist it can only fetch /sub through the live tunnel).
        if now >= st["swap_deadline"]:
            # HARD GATE: never tear the current room down until the client's OWN
            # latest /sub is KNOWN to have delivered BOTH the current room AND the
            # standby it must hop to. If it isn't in the client's list, killing the
            # current room strands it - on a whitelist it then cannot even re-fetch
            # /sub to learn a new room -> permanent death. `delivered_rooms` records
            # exactly what the last /sub handed this client, so we check the actual
            # rooms, not just "a fetch happened after we advertised". If the client
            # hasn't received the pair yet we DEFER (keep the live room) - worst case
            # is a late swap, never a dead tunnel.
            delivered = RoomState.delivered_rooms(tag, short_uuid)
            sb_room = st.get("standby_room")
            srv_up = bool(st.get("standby")) and await RoomRotator._srv_connected(
                st["standby"]
            )
            client_has_current = current_room in delivered
            client_has_standby = bool(sb_room) and sb_room in delivered
            fetched_ok = RoomState.fetched_after(
                short_uuid, st.get("standby_advertised_at") or now
            )
            # The client must be ON the current room right now, not merely holding
            # its id from a /sub fetch. Without this the first fetch after a HELD
            # deadline opens the gate instantly and the swap kills the room the
            # client is in the middle of dialling.
            client_live = await RoomRotator._client_attached(name)
            ready = bool(
                sb_room and srv_up and client_has_current and client_has_standby
                and fetched_ok and client_live
            )
            if ready:
                RoomRotator._log(
                    f"{name}: SWAP ok - client has current={current_room} + standby={sb_room} "
                    f"(client_list={sorted(delivered)})"
                )
                await RoomRotator._rotate(
                    profile, provider, tokens, tag, short_uuid, st, "scheduled"
                )
            else:
                # Standby warming/flapping, or the client hasn't fetched the standby
                # room (offline). Keep waiting - but never ride the CURRENT room to
                # its ~24h death: if it is about to expire, force a rotation now.
                RoomRotator._log(
                    f"{name}: swap HELD (deadline passed) - srv_up={srv_up} "
                    f"client_live={client_live} "
                    f"client_has_current={client_has_current} "
                    f"client_has_standby={client_has_standby} "
                    f"standby={sb_room} client_list={sorted(delivered)}"
                )
                expiry = st["current_created"] + ROOM_LIFETIME_SECONDS
                if now >= expiry - BROKEN_BUFFER_SECONDS:
                    await RoomRotator._rotate(
                        profile, provider, tokens, tag, short_uuid, st, "near expiry"
                    )
        return

    @staticmethod
    async def _reap_dead_tokens(profiles) -> None:
        """Prune tokens confirmed dead (401/403 on BOTH realms) from profile
        configs so the panel shows only the survivors. Does NOT restart
        containers - the live tunnel stays up."""
        dead = set(RoomGenerator._confirmed_dead)
        if not dead:
            return
        for profile in profiles:
            cfg = RoomRotator._parse(profile.profile)
            auth = cfg.get("auth") or {}
            if auth.get("provider") != "telemost":
                continue
            # Keep each entry's shape (a plain string, or a managed {token,account}
            # dict). Drop only PLAIN dead strings; managed entries are NEVER pruned
            # (they get refreshed by _refresh_managed_tokens instead).
            entries: list = []
            single = auth.get("token")
            if isinstance(single, str):
                entries.append(single)
            multi = auth.get("tokens")
            if isinstance(multi, list):
                entries.extend(multi)
            removed = 0
            survivors: list = []
            for e in entries:
                if isinstance(e, str):
                    if e.strip() in dead:
                        removed += 1
                    else:
                        survivors.append(e)
                else:
                    survivors.append(e)  # managed dict - always kept
            if removed == 0:
                continue
            auth.pop("token", None)
            auth.pop("tokens", None)
            plain = [s for s in survivors if isinstance(s, str)]
            if len(survivors) == 1 and plain:
                auth["token"] = plain[0]
            elif survivors:
                auth["tokens"] = survivors  # mixed plain + managed preserved
            cfg["auth"] = auth
            new_yaml = yaml.safe_dump(cfg, sort_keys=False)
            try:
                await Profiles.save_no_restart(profile.tag, profile.name, new_yaml)
                RoomRotator._log(
                    f"{profile.tag}: pruned {removed} dead plain token(s) "
                    f"({len(survivors)} entr(y/ies) left)"
                )
            except Exception as exc:
                RoomRotator._log(f"{profile.tag}: failed to prune dead tokens: {exc}")
        for t in dead:
            RoomGenerator._confirmed_dead.discard(t)
            RoomGenerator._dead_tokens.pop(t, None)

    @staticmethod
    async def _refresh_managed_tokens(profiles) -> None:
        """Pull a fresh Session_id from the vault for every managed token
        ({token, account}) and write it back to the profile (no container
        restart). Called on a slow timer - the vault's browser spin-up per
        account is heavy and the token lives ~1 month."""
        from profiles.vault_client import Vault
        if not Vault.configured():
            return
        for profile in profiles:
            cfg = RoomRotator._parse(profile.profile)
            auth = cfg.get("auth") or {}
            if auth.get("provider") != "telemost":
                continue
            toks = auth.get("tokens")
            if not isinstance(toks, list):
                continue
            changed = False
            for entry in toks:
                if not isinstance(entry, dict):
                    continue
                account = entry.get("account")
                if not account:
                    continue
                fresh = await Vault.get_token(account)
                if fresh and fresh != entry.get("token"):
                    entry["token"] = fresh
                    changed = True
                    RoomRotator._log(
                        f"{profile.tag}: refreshed managed token for account {account}"
                    )
            if changed:
                cfg["auth"] = auth
                new_yaml = yaml.safe_dump(cfg, sort_keys=False)
                try:
                    await Profiles.save_no_restart(profile.tag, profile.name, new_yaml)
                except Exception as exc:
                    RoomRotator._log(f"{profile.tag}: failed to save refreshed tokens: {exc}")

    @staticmethod
    async def _rotate_once() -> None:
        profiles = await Profiles.get_all()

        # Periodically refresh managed (vault-backed) tokens so the stored
        # Session_id never goes stale (runs immediately on first cycle / restart).
        now = RoomRotator._now()
        if now - RoomRotator._last_token_refresh >= TOKEN_REFRESH_INTERVAL:
            RoomRotator._last_token_refresh = now
            await RoomRotator._refresh_managed_tokens(profiles)

        # Prune tokens confirmed dead on BOTH realms from the profile configs
        # (so the panel reflects it), without touching the live containers.
        if RoomGenerator._confirmed_dead:
            await RoomRotator._reap_dead_tokens(profiles)

        # tag -> (profile, provider, tokens) for telemost profiles with >= 2 tokens
        targets: dict[str, tuple] = {}
        for profile in profiles:
            cfg = RoomRotator._parse(profile.profile)
            provider = (cfg.get("auth") or {}).get("provider")
            if provider != "telemost":
                continue
            tokens = Subscriptions.profile_tokens(cfg)
            if len(tokens) >= MIN_TOKENS_FOR_ROTATION:
                targets[profile.tag] = (profile, provider, tokens)

        containers = await Containers.all()

        # Put rooms that are already being served back in the pool before anything
        # reads their age.
        await RoomRotator._adopt_running_rooms(containers, targets)

        # Forget state for containers that no longer exist.
        live_names = {c.name for c in containers}
        for stale in list(RoomRotator._state.keys()):
            if stale not in live_names:
                RoomRotator._state.pop(stale, None)
                RoomRotator._dead_strikes.pop(stale, None)

        # Standby containers are 4-part named -> invisible to Containers.all(), so
        # scan raw docker. One that no slot is tracking is either an orphan from a
        # crash mid-cutover, or ours from before a restart. ADOPT it when its slot
        # is live and standby-less: it is a warm server already sitting in a room
        # the connected client was told about, so destroying it would leave that
        # client with a single live room until its next subscription fetch.
        tracked = {
            s.get("standby") for s in RoomRotator._state.values() if s.get("standby")
        }
        try:
            for cont in await OlcRTC.all(include_stopped=True):
                info = await cont.show()
                nm = info["Name"].lstrip("/")
                if (
                    not nm.startswith("olcwave-")
                    or not nm.endswith(STANDBY_SUFFIX)
                    or nm in tracked
                ):
                    continue
                owner = nm[: -len(STANDBY_SUFFIX)]
                st = RoomRotator._state.get(owner)
                running = (info.get("State") or {}).get("Running") is True
                if st is None and owner in live_names:
                    # The slot is live but has no state yet - this tick's _tick
                    # will create it. Deciding now would destroy a warm standby
                    # purely because we happen to run before that. Leave it for
                    # the next tick, when the adoption test below can be answered.
                    continue
                if st is not None and running and not st.get("standby"):
                    room = await RoomRotator._current_room_id(nm)
                    if room and room != await RoomRotator._current_room_id(owner):
                        st["standby"] = nm
                        st["standby_room"] = room
                        RoomRotator._log(f"adopted existing standby {nm} on {room}")
                        continue
                await OlcRTC.remove(nm)
                RoomRotator._log(f"reaped orphan standby {nm}")
        except Exception:
            pass

        if not targets:
            return

        run_targets = [
            c for c in containers
            if c.config_tag in targets and c.status == "running"
        ]

        for container in run_targets:
            profile, provider, tokens = targets[container.config_tag]
            try:
                await RoomRotator._tick(profile, provider, tokens, container)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                RoomRotator._log(f"tick failed for {container.name} (ignored): {exc}")

    @staticmethod
    async def run() -> None:
        RoomRotator._log("started")
        try:
            await RoomRotator.restore()
        except Exception as exc:
            # A restart with no memory is the old behaviour, not an outage.
            RoomRotator._log(f"resume failed, starting cold: {exc}")
        while True:
            try:
                await RoomRotator._rotate_once()
                await RoomRotator._persist()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                RoomRotator._log(f"cycle failed (ignored): {exc}")
            await asyncio.sleep(RoomRotator._cadence()["tick"])
