import asyncio
import random
import secrets
from typing import Any

import emoji
import yaml

from fastapi import Response

from config import settings
from locks import get_user_lock
from room_state import RoomState
from settings.service import SettingsService
from users.schemas import TrafficInfoSchema, UserSchema
from olcrtc.sdk import OlcRTC
from profiles.roomGenerator import RoomChecker, RoomGenerator
from profiles.service import Containers
from profiles.service import Profiles
from users.service import Users


TRANSPORT_NAMES = {
    "vp8channel": "vp8",
    "seichannel": "sei",
    "videochannel": "video",
}

TRANSPORT_OPTIONS = {
    "vp8": {
        "fps": "vp8-fps",
        "batch_size": "vp8-batch",
    },
    "sei": {
        "fps": "fps",
        "batch_size": "batch",
        "fragment_size": "frag",
        "ack_timeout_ms": "ack-ms",
    },
    "video": {
        "width": "video-w",
        "height": "video-h",
        "fps": "video-fps",
        "bitrate": "video-bitrate",
        "hw": "video-hw",
        "codec": "video-codec",
        "qr_size": "video-qr-size",
        "qr_recovery": "video-qr-recovery",
        "tile_module": "video-tile-module",
        "tile_rs": "video-tile-rs",
    },
}


def bytes_to_notation(num: float):
    notations = ["b", "kb", "mb", "gb", "tb"]
    ptr = 0
    while num > 1000 and ptr < len(notations) - 1:
        num /= 1000
        ptr += 1

    return f"{int(num)}{notations[ptr]}"


class Subscriptions:
    @staticmethod
    def remove_last_emoji(s: str) -> tuple[str, str]:
        matches = list(emoji.emoji_list(s))
        if not matches:
            return s, ""

        last = matches[-1]

        return (
            s[:last["match_start"]] + s[last["match_end"]:],
            last["emoji"],
        )

    @staticmethod
    def profile_tokens(config: dict) -> list[str]:
        """All Session_id tokens configured in a profile's YAML.

        Supports a single `auth.token` (legacy / 1-token profile) and a list
        `auth.tokens` (multi-account profile). 1 token = single autogen (no
        rotation); >= 2 tokens = the RoomRotator rotates rooms across them.
        A `auth.tokens` entry may also be a managed/self-refreshing token
        `{token: <sid>, account: <vault_key>}` (the vault keeps the `token`
        fresh); here we just yield its current `token` so everything downstream
        sees a normal Session_id list.
        """
        auth = config.get("auth") or {}
        out: list[str] = []
        single = auth.get("token")
        if isinstance(single, str) and single.strip():
            out.append(single.strip())
        multi = auth.get("tokens")
        if isinstance(multi, list):
            for t in multi:
                if isinstance(t, str) and t.strip():
                    out.append(t.strip())
                elif isinstance(t, dict):
                    tok = t.get("token")
                    if isinstance(tok, str) and tok.strip():
                        out.append(tok.strip())

        seen: set[str] = set()
        unique: list[str] = []
        for t in out:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique

    @staticmethod
    async def profile_to_config(
        profile: str,
        force_room_id: str | None = None,
        force_key: str | None = None,
    ):
        config = yaml.safe_load(profile)
        config.pop("data", None)
        # A failover group shares one key across its rooms; the rotator passes the
        # group's key here so the next room joins the same tunnel secret.
        config.setdefault("crypto", {})["key"] = force_key or secrets.token_hex(32)

        provider = config["auth"]["provider"]

        if force_room_id is not None:
            # Proactive rotation supplies an already-minted room id.
            config["room"] = config.get("room", {})
            config["room"]["id"] = force_room_id
        elif (
            provider in ["telemost", "wbstream"]
            and config.get("room", {}).get("id", "") == ""
        ):
            # Reactive autogen: mint a room from the profile's tokens, rolling
            # past any dead ones. RoomGenerator.mint_room tries .ru->.com per
            # token and drops corpses from the active pool; None = every token
            # dead (TODO: fall back to the running container's room instead of
            # raising, so /sub never 500s - separate follow-up).
            tokens = Subscriptions.profile_tokens(config)
            if tokens:
                room_id = await RoomGenerator.mint_room(provider, tokens)
                if not room_id:
                    raise RuntimeError("all tokens dead - could not mint a room")
                config["room"] = config.get("room", {})
                config["room"]["id"] = room_id

        if provider == "telemost":
            # Tokens are server-only: never ship them to the client config.
            config["auth"].pop("token", None)
            config["auth"].pop("tokens", None)

        if provider == "jitsi":
            room_url = config["room"]["id"].split("/")

            if len(room_url) == 3:
                room_url.append(
                    str(secrets.token_hex(16))
                )

            elif len(room_url) == 4 and not room_url[3]:
                room_url[3] = str(secrets.token_hex(16))

            config["room"]["id"] = "/".join(room_url)
        return yaml.dump(config)

    @staticmethod
    def build_transport_options(cfg: dict) -> str:
        transport = cfg["net"]["transport"]

        if transport == "datachannel":
            return ""

        short = TRANSPORT_NAMES[transport]

        params = "&".join(
            f"{TRANSPORT_OPTIONS[short][k]}={v}"
            for k, v in cfg[short].items()
        )

        return f"<{params}>"

    @staticmethod
    def config_to_uri(config: str, name: str) -> str:
        cfg = yaml.safe_load(config)

        options = Subscriptions.build_transport_options(cfg)

        return (
            f"olcrtc://{cfg['auth']['provider']}?"
            f"{cfg['net']['transport']}"
            f"{options}"
            f"@{cfg['room']['id']}#"
            f"{cfg['crypto']['key']}${name}"
        )

    @staticmethod
    async def get_launched_tags(short_uuid: str):
        servers = []

        for srv in await OlcRTC.all():
            if await Containers.is_panel_container(srv):
                info = await srv.show()
                name = info["Name"].lstrip("/")

                if name.endswith(short_uuid):
                    servers.append(
                        name.split("-", 2)[1]
                    )

        return servers

    @staticmethod
    def prepare_sub_text(
        entries: list[tuple[str, list[str]]],
        name: str,
        used: int = 0,
        limit: int = 0,
    ):
        txt = (
            f"#name: {name}\n"
            f"#update: 2147483647\n"
            f"#refresh: {SettingsService.get().sub_update_interval}\n"
        )
        if limit == 0:
            txt += f"#used: {bytes_to_notation(used)}\n"
        else:
            txt += (
                f"#used: {bytes_to_notation(used)}/"
                f"{bytes_to_notation(limit)}\n"
                f"#available: "
                f"{bytes_to_notation(limit-used)}\n\n"
            )

        for uri, extra_rooms in entries:
            label = uri[uri.find("$") + 1:]

            label, icon = Subscriptions.remove_last_emoji(label)

            txt += (
                f"{uri}\n"
                f"##name: {label}\n"
            )

            # Failover-group extras: rooms sharing this location's key that a
            # dynamic-list client adds to its in-process failover set. Old clients
            # ignore ##rooms and just use the primary room above.
            if extra_rooms:
                txt += f"##rooms: {' '.join(extra_rooms)}\n"

            if icon:
                txt += f"##icon: {icon}\n"

        return txt

    @staticmethod
    async def _cleanup_user_containers(short_uuid: str):
        for container in await OlcRTC.all(True):
            info = await container.show()
            name = info["Name"].lstrip("/")

            if (
                name.startswith("olcwave-")
                and name.endswith(f"-{short_uuid}")
            ):
                await OlcRTC.remove(name)

    @staticmethod
    async def _validate_rw_user(short_uuid: str) -> Any | None:
        from rw.sdk import isUserValid
        rw_user = await isUserValid(short_uuid)
        if rw_user:
            return rw_user
        return None

    @staticmethod
    async def _ensure_local_user_from_rw(short_uuid: str, rw_user: Any):
        try:
            await Users.get(short_uuid)
        except Exception:
            await Users.add(
                UserSchema(
                    short_uuid=short_uuid,
                    name=rw_user.user.username,
                    expires_at=rw_user.user.expires_at,
                )
            )

    @staticmethod
    def traffic_limit_response(traffic: TrafficInfoSchema):
        traffic_uri = (
            "olcrtc://wbstream?"
            "datachannel@0#"
            "0000000000000000000000000000000000000000000000000000000000000000"
            "$Traffic limit exceeded"
        )

        return Response(
            content=Subscriptions.prepare_sub_text(
                [(traffic_uri, [])],
                SettingsService.get().sub_name,
                traffic.used,
                traffic.limit,
            ),
            status_code=403,
            media_type="text/plain",
        )

    @staticmethod
    async def ensure_profiles_running(short_uuid: str):

        try:
            user = await Users.get(short_uuid)
            allowed_tags = user.profiles  # None = all profiles, list = only those
        except Exception:
            allowed_tags = None

        running_tags = await Subscriptions.get_launched_tags(
            short_uuid
        )

        async def load_config(tag):

            container_name = (
                f"olcwave-{tag}-{short_uuid}"
            )

            config = await OlcRTC.get_config(
                container_name
            )

            if isinstance(config, bytes):
                config = config.decode()

            return tag, config

        loaded = await asyncio.gather(
            *(load_config(tag) for tag in running_tags)
        )

        configs = dict(loaded)

        async def check_profile(tag, config):
            try:
                obj = yaml.safe_load(config)

                provider = obj["auth"]["provider"]

                if provider in ("telemost", "wbstream"):

                    exists = await RoomChecker.check_room_id(
                        provider,
                        obj["room"]["id"],
                        obj["auth"].get("token", ""),
                    )

                    if not exists:
                        await OlcRTC.remove(
                            f"olcwave-{tag}-{short_uuid}"
                        )
            except Exception as exc:
                # A liveness-check / removal hiccup for one profile must not fail
                # the whole /sub; leave the container as-is and move on.
                print(
                    f"[sub] {tag}/{short_uuid}: check_profile error, ignored: {exc}",
                    flush=True,
                )

        await asyncio.gather(
            *(check_profile(tag, cfg)
              for tag, cfg in configs.items())
        )

        profiles_list = await Profiles.get_all()

        if allowed_tags is not None:
            profiles_list = [
                profile
                for profile in profiles_list
                if profile.tag in allowed_tags
            ]

        profiles = {
            profile.tag: profile
            for profile in profiles_list
        }

        # Stop and drop containers for profiles this user may no longer use
        # (unassigned from the user, or the profile was deleted).
        for tag in list(configs.keys()):
            if tag not in profiles:
                try:
                    await OlcRTC.remove(f"olcwave-{tag}-{short_uuid}")
                except Exception:
                    pass
                configs.pop(tag, None)

        missing = profiles.keys() - configs.keys()

        async def start_profile(tag):
            try:
                config = await Subscriptions.profile_to_config(
                    profiles[tag].profile
                )
                await Containers.run(
                    config,
                    tag,
                    short_uuid,
                )
            except Exception as exc:
                # Could not bring this profile up (e.g. every token is dead and no
                # live pooled room to reuse). Skip THIS profile instead of failing
                # the whole /sub - the other profiles still render, and the client
                # keeps whatever rooms it already had for this one.
                print(
                    f"[sub] {tag}/{short_uuid}: cannot start profile, skipped: {exc}",
                    flush=True,
                )
                return

            configs[tag] = config

        await asyncio.gather(
            *(start_profile(tag) for tag in missing)
        )

        return configs, profiles

    @staticmethod
    async def get(short_uuid: str):
        if settings.RW_ENABLED:
            rw_user = await Subscriptions._validate_rw_user(short_uuid)
            if rw_user is None:
                await Subscriptions._cleanup_user_containers(short_uuid)
                return Response(status_code=404)

            await Subscriptions._ensure_local_user_from_rw(short_uuid, rw_user)
        else:
            try:
                await Users.get(short_uuid)
            except Exception:
                return Response(status_code=404)

        traffic = await Users.get_traffic(short_uuid)
        if traffic.exceeded:
            return Subscriptions.traffic_limit_response(
                traffic
            )

        async with get_user_lock(short_uuid):
            configs, profiles = await Subscriptions.ensure_profiles_running(
                short_uuid
            )

        # The container's current room is always the PRIMARY (it holds the live
        # srv). During a handoff the rotator advertises the freshly minted NEXT
        # room(s) here as failover extras (##rooms) sharing the primary's key, so
        # a dynamic-list client can hop to them in-process before the old room is
        # torn down. Old single-room clients ignore ##rooms and use the primary.
        entries = []
        for tag in profiles:
            config = configs.get(tag)
            if config is None:
                # Profile could not be started (no room available). Omit it so the
                # rest of the subscription still renders instead of 500ing.
                continue
            uri = Subscriptions.config_to_uri(config, profiles[tag].name)
            extra_rooms = RoomState.get_advertised(tag, short_uuid) or []
            entries.append((uri, extra_rooms))
            # Record exactly which rooms this /sub hands the client (the primary
            # room + the ##rooms failover extras) so the rotator can gate a swap on
            # the client REALLY having received the standby together with the
            # current room - not just on "a fetch happened".
            primary_room = (yaml.safe_load(config).get("room") or {}).get("id")
            delivered_rooms = set(extra_rooms)
            if primary_room:
                delivered_rooms.add(primary_room)
            RoomState.note_delivered(tag, short_uuid, delivered_rooms)
            print(
                f"[sub] {short_uuid}/{tag}: delivered rooms {sorted(delivered_rooms)} "
                f"(primary={primary_room}, ##rooms={list(extra_rooms)})",
                flush=True,
            )

        # A successful fetch is the rotation ACK: on a whitelist the client only
        # reaches /sub through the live tunnel, so this proves it received the
        # rooms advertised above.
        RoomState.note_fetch(short_uuid)

        return Response(
            content=Subscriptions.prepare_sub_text(
                entries,
                SettingsService.get().sub_name,
                traffic.used,
                traffic.limit,
            ),
            media_type="text/plain",
        )
