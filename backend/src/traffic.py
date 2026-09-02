import asyncio

from settings.service import SettingsService
from olcrtc.sdk import OlcRTC
from olcrtc.service import Containers
from users.service import Users


class TrafficManager:
    """Background traffic accounting and limit enforcement."""

    _last_totals: dict[str, int] = {}

    @staticmethod
    def _owner_of(name: str) -> str | None:
        # maxsplit=2: Remnawave shortUuid contains hyphens
        parts = name.split("-", 2)

        if len(parts) == 3 and parts[0] == "olcwave":
            return parts[2]

        return None

    @staticmethod
    async def _collect_deltas() -> dict[str, int]:
        deltas: dict[str, int] = {}
        seen: set[str] = set()

        containers = await OlcRTC.all(include_stopped=False)
        for cont in containers:
            info = await cont.show()

            name = info["Name"].lstrip("/")

            if not await Containers.is_panel_container(cont):
                continue

            owner = TrafficManager._owner_of(name)

            if owner is None:
                continue

            seen.add(name)

            stats = await Containers.get_stats(name)

            total = stats.total_bytes

            previous = TrafficManager._last_totals.get(name, total)

            # container restart resets counter
            delta = (
                total - previous
                if total >= previous
                else total
            )

            TrafficManager._last_totals[name] = total

            if delta > 0:
                deltas[owner] = (
                    deltas.get(owner, 0) + delta
                )

        for gone in (
            set(TrafficManager._last_totals) - seen
        ):
            del TrafficManager._last_totals[gone]

        return deltas

    @staticmethod
    async def _stop_user_containers(short_uuid: str):
        containers = await OlcRTC.all(include_stopped=False)

        for cont in containers:
            info = await cont.show()

            name = info["Name"].lstrip("/")

            if not await Containers.is_panel_container(cont):
                continue

            if TrafficManager._owner_of(name) != short_uuid:
                continue

            try:
                await OlcRTC.stop(name)

            except Exception:
                pass

    @staticmethod
    async def _tick():
        deltas = await TrafficManager._collect_deltas()
        for short_uuid, delta in deltas.items():
            try:
                await Users.add_traffic_used(short_uuid, delta)

                info = await Users.get_traffic(short_uuid)

                if info.exceeded:
                    await TrafficManager._stop_user_containers(short_uuid)

            except Exception:
                # one broken user should not kill loop
                continue

    @staticmethod
    async def run():
        while True:
            try:
                await TrafficManager._tick()

            except asyncio.CancelledError:
                raise

            except Exception:
                pass

            await asyncio.sleep(
                SettingsService.get().traffic_collect_interval
            )