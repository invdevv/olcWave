import hashlib
import random
import time
import uuid

import httpx
from fake_useragent import UserAgent


class TokenAuthDead(RuntimeError):
    """Both Yandex realms (.ru AND .com) rejected the Session_id with an auth
    error (401/403) -> the token is genuinely dead everywhere and should be
    pruned from the profile config. A 5xx/timeout/network error is NOT this (it
    is transient), so a Yandex outage never deletes tokens."""


class RoomGenerator:
    # Session_id tokens that failed to mint on BOTH .ru and .com are parked here
    # (token -> monotonic time of death) and dropped from the active pool. They
    # revive after DEAD_TOKEN_TTL (self-heals a transient blip); a token the user
    # replaces is a new string, so it is active immediately. Reset on restart.
    _dead_tokens: dict[str, float] = {}
    DEAD_TOKEN_TTL = 60 * 60

    # Tokens confirmed dead (401/403 on BOTH realms). The rotator drains this set
    # and prunes these tokens from the profile config, then clears it.
    _confirmed_dead: set[str] = set()

    # token -> [{"room": id, "created": epoch}] : POOL_PER_TOKEN live rooms per
    # token that we REUSE instead of always minting fresh. Rooms older than
    # ROOM_MAX_AGE are pruned (Telemost instant rooms die ~24h).
    #
    # Persisted across restarts via snapshot()/restore() - see persistence.py.
    # Losing it used to mean refilling with brand-new rooms that no connected
    # client could learn, and forgetting every room's real birth, which is what
    # the expiry guard measures against.
    _pools: dict[str, list[dict]] = {}
    POOL_PER_TOKEN = 2         # fixed live rooms kept per token (full set = per_token * #tokens)
    ROOM_MAX_AGE = 18 * 3600   # a pooled room older than this is dropped + replenished

    @staticmethod
    def _now() -> float:
        # Wall clock, to match room_rotator's time.time() bookkeeping so a pooled
        # room's birth is directly comparable to the rotator's current_created.
        return time.time()

    @staticmethod
    def _fp(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()[:8]

    @staticmethod
    def snapshot() -> dict:
        """JSON-able view of the pool, keyed by token FINGERPRINT.

        The in-memory dicts are keyed by the Session_id itself, which is a full
        account credential - it must not reach storage. The fingerprint is enough
        to reattach a pool to its token on restore, and is useless on its own.
        """
        return {
            "pools": {
                RoomGenerator._fp(tok): [
                    {"room": r["room"], "created": r["created"]} for r in rooms
                ]
                for tok, rooms in RoomGenerator._pools.items()
            },
            "dead_tokens": {
                RoomGenerator._fp(tok): died
                for tok, died in RoomGenerator._dead_tokens.items()
            },
        }

    @staticmethod
    def restore(data: dict | None, tokens: list[str]) -> int:
        """Reattach a snapshot to the CURRENT tokens by fingerprint.

        A token the user has since replaced is a new string with a new
        fingerprint, so its stale pool is simply not claimed - which is the
        behaviour we want. Returns how many rooms were restored.
        """
        if not isinstance(data, dict):
            return 0
        by_fp = {RoomGenerator._fp(t): t for t in tokens}
        restored = 0

        for fp, rooms in (data.get("pools") or {}).items():
            token = by_fp.get(fp)
            if token is None or not isinstance(rooms, list):
                continue
            pool = RoomGenerator._pools.setdefault(token, [])
            known = {r["room"] for r in pool}
            for record in rooms:
                try:
                    room, created = record["room"], float(record["created"])
                except Exception:
                    continue
                if room in known:
                    continue
                pool.append({"room": room, "created": created})
                known.add(room)
                restored += 1
            # Drop anything that aged out while we were down.
            RoomGenerator._prune_pool(pool)

        for fp, died in (data.get("dead_tokens") or {}).items():
            token = by_fp.get(fp)
            if token is not None and isinstance(died, (int, float)):
                RoomGenerator._dead_tokens.setdefault(token, float(died))

        return restored

    @staticmethod
    def adopt_room(token: str, room_id: str, created: float | None = None) -> None:
        """Put a room we already know is in use into its token's pool.

        Rooms live in running containers, which outlive us. Without this a
        restart would leave the room a client is CONNECTED to absent from the
        pool - so `room_created_at` returns None, its real age is lost, and the
        expiry guard starts counting from the wrong birth.
        """
        pool = RoomGenerator._pools.setdefault(token, [])
        if any(r["room"] == room_id for r in pool):
            return
        pool.append({"room": room_id, "created": created or RoomGenerator._now()})

    @staticmethod
    def _active_tokens(tokens: list[str]) -> list[str]:
        now = RoomGenerator._now()
        out = []
        for t in tokens:
            died = RoomGenerator._dead_tokens.get(t)
            if died is None or (now - died) >= RoomGenerator.DEAD_TOKEN_TTL:
                out.append(t)
        return out

    @staticmethod
    def _prune_pool(pool: list[dict]) -> None:
        now = RoomGenerator._now()
        pool[:] = [
            r for r in pool
            if (now - r["created"]) < RoomGenerator.ROOM_MAX_AGE
        ]

    @staticmethod
    def room_created_at(room_id: str) -> float | None:
        """Epoch this room was minted, if still pooled (for the rotator's hold
        capping / expiry math on a REUSED old room). None if unknown."""
        for pool in RoomGenerator._pools.values():
            for r in pool:
                if r["room"] == room_id:
                    return r["created"]
        return None

    @staticmethod
    async def room_alive(provider: str, room_id: str) -> bool | None:
        """True = alive, False = the provider says it does not exist, None = we
        could not find out.

        The three cases are NOT interchangeable. `False` here means Telemost
        actually answered "no such meeting"; a timeout, a 5xx or a captcha page
        raises or reads as alive, and comes back as None or True rather than as a
        death sentence for a room a client may be sitting in.
        """
        try:
            return await RoomChecker.check_room_id(provider, room_id, "")
        except Exception:
            return None

    @staticmethod
    async def _fill_token_pool(provider: str, tok: str, per_token: int) -> list[str]:
        """Top a single token up to `per_token` LIVE rooms: drop aged ones, mint to
        refill. Returns the token's current room ids. A both-realm auth failure flags
        the token dead (for config prune) and stops filling it this round."""
        pool = RoomGenerator._pools.setdefault(tok, [])
        RoomGenerator._prune_pool(pool)                   # drop rooms too old to keep
        while len(pool) < per_token:
            try:
                room = await RoomGenerator.generate_room_id(provider, tok)
            except Exception as exc:
                RoomGenerator._dead_tokens[tok] = RoomGenerator._now()
                if isinstance(exc, TokenAuthDead):
                    RoomGenerator._confirmed_dead.add(tok)
                    print(
                        f"[room-pool] token fp={RoomGenerator._fp(tok)} CONFIRMED DEAD "
                        f"(401/403 on .ru+.com) - will be pruned from the profile: {exc}",
                        flush=True,
                    )
                else:
                    print(
                        f"[room-pool] token fp={RoomGenerator._fp(tok)} fill failed "
                        f"(transient?), skipped for now: {exc}",
                        flush=True,
                    )
                break
            if room:
                RoomGenerator._dead_tokens.pop(tok, None)
                pool.append({"room": room, "created": RoomGenerator._now()})
        return [r["room"] for r in pool]

    @staticmethod
    async def ensure_pool(
        provider: str, tokens: list[str], per_token: int | None = None
    ) -> list[str]:
        """Fill every ACTIVE token to `per_token` live rooms and return the whole set
        as a flat list. This is the fixed room pool the rotator cycles through; a
        room that ages out is replenished here so the pool stays full."""
        per_token = per_token or RoomGenerator.POOL_PER_TOKEN
        rooms: list[str] = []
        for tok in RoomGenerator._active_tokens(tokens):
            rooms.extend(await RoomGenerator._fill_token_pool(provider, tok, per_token))
        return rooms

    @staticmethod
    async def mint_room(
        provider: str, tokens: list[str], exclude: set[str] | None = None
    ) -> str | None:
        """Pick a random room from the FIXED pool that is not in `exclude`.

        The pool is a fixed set (POOL_PER_TOKEN rooms per live token), (re)filled
        here. `exclude` carries the rooms currently IN PLAY - the current primary,
        the just-vacated room the client may still be reconnecting to, and the live
        standby - so we never hand back a room the client is still latched onto (that
        is what made a killed room get resurrected and re-glue the client). Returns
        None only when the pool is empty or every room is excluded; the caller then
        keeps the current live room (never tears the tunnel down)."""
        exclude = exclude or set()
        pool = await RoomGenerator.ensure_pool(provider, tokens)
        candidates = [r for r in pool if r not in exclude]
        if candidates:
            return random.choice(candidates)
        if pool:
            print(
                f"[room-pool] all {len(pool)} pooled room(s) excluded "
                f"{sorted(exclude)} - no distinct room this tick",
                flush=True,
            )
        return None
    @staticmethod
    async def generate_room_id(provider: str, token: str) -> str:
        providers_funcs= {
            "telemost": RoomGenerator._generate_telemost_room_id,
            "wbstream": RoomGenerator._generate_wbstream_room_id,
        }

        generate = providers_funcs.get(provider)
        if generate is None:
            raise RuntimeError(f"Provider {provider} not supported for room generation")

        roomId = await generate(token)

        return roomId

    @staticmethod
    async def _generate_wbstream_room_id(token: str) -> str:
        ua = UserAgent()

        headers = {
            "User-Agent": ua.random,
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Referer": "https://stream.wb.ru/",
            "authorization": f"Bearer {token}",
            "Origin": "https://stream.wb.ru",
        }

        async with httpx.AsyncClient() as client:
            res = await client.post(
                url = "https://stream.wb.ru/api-room/api/v2/room",
                headers=headers,
                json = {"roomType":"ROOM_TYPE_ALL_ON_SCREEN","roomPrivacy":"ROOM_PRIVACY_FREE"}
            )

        return res.json()["roomId"]

    @staticmethod
    async def _generate_telemost_room_id(token: str) -> str:
        # Yandex Session_id is realm-bound: a yandex.ru session authenticates only
        # against cloud-api.yandex.ru, a yandex.com session only against .com. Try
        # .ru first and fall back to .com so a mixed .ru/.com token pool works.
        # (Strategy for when BOTH realms refuse is a separate follow-up.)
        endpoints = [
            (
                "https://cloud-api.yandex.ru/telemost_front/v2/telemost/conferences?next_gen_media_platform_allowed=true",
                "https://telemost.yandex.ru",
            ),
            (
                "https://cloud-api.yandex.com/telemost_front/v2/telemost/conferences?next_gen_media_platform_allowed=true",
                "https://telemost.yandex.com",
            ),
        ]

        cookies = {"Session_id": token}
        statuses: list[int | None] = []   # per realm: HTTP status, or None on network error
        last_body = ""

        async with httpx.AsyncClient() as client:
            for url, origin in endpoints:
                ua = UserAgent()
                headers = {
                    "User-Agent": ua.random,
                    "Accept": "*/*",
                    "Content-Type": "application/json",
                    "Client-Instance-Id": str(uuid.uuid4()),
                    "X-Telemost-Client-Version": "203.1.0",
                    "Idempotency-Key": str(uuid.uuid4()),
                    "Origin": origin,
                    "Referer": origin + "/",
                }

                try:
                    res = await client.post(url, headers=headers, cookies=cookies, json={})
                except Exception:
                    statuses.append(None)   # network/transient - still try the other realm
                    continue

                try:
                    data = res.json()
                except Exception:
                    data = None

                if isinstance(data, dict) and "uri" in data:
                    return data["uri"].split("/")[-1]

                statuses.append(res.status_code)
                last_body = res.text[:300]

        # Both realms failed. A 401/403 on BOTH means "this session is not valid
        # anywhere" -> genuinely dead -> TokenAuthDead (config prune). Anything else
        # (5xx/429/timeout/network) is transient -> plain RuntimeError (in-memory
        # skip + retry later), so a Yandex outage never deletes tokens.
        msg = f"telemost mint failed on .ru/.com: statuses={statuses}, body={last_body!r}"
        if statuses and all(s in (401, 403) for s in statuses):
            raise TokenAuthDead(msg)
        raise RuntimeError(msg)



class RoomChecker:
    @staticmethod
    async def check_room_id(provider: str, room_id: str, token: str) -> bool:
        providers_funcs= {
            "telemost": RoomChecker._check_telemost_room_id,
            "wbstream": RoomChecker._check_wbstream_room_id,
        }

        check = providers_funcs.get(provider)
        if check is None:
            raise RuntimeError(f"Provider {provider} not supported for room generation")

        roomId = await check(room_id, token)

        return roomId

    @staticmethod
    async def _check_wbstream_room_id(room_id:str, token: str) -> bool:
        ua = UserAgent()

        headers = {
            "User-Agent": ua.random,
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Referer": f"https://stream.wb.ru/room/{room_id}",
            "authorization": f"Bearer {token}",
            "Origin": "https://stream.wb.ru",
        }


        async with httpx.AsyncClient() as client:
            res = await client.get(
                url = f"https://stream.wb.ru/api-room/api/v1/room/{room_id}",
                headers=headers,
            )

        return res.status_code == 200

    @staticmethod
    async def _check_telemost_room_id(room_id:str, *agrs, **kwargs) -> bool:
        ua = UserAgent()

        headers = {
            "User-Agent": ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Origin": "https://telemost.yandex.ru",
            "Referer": "https://telemost.yandex.ru/",
        }


        async with httpx.AsyncClient() as client:
            res = await client.get(
                url = f"https://telemost.yandex.ru/j/{room_id}",
                headers=headers
            )
        
        return "Такой встречи не существует" not in res.text