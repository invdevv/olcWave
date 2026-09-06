import asyncio

from aiodocker.containers import DockerContainer

from xraycore.sdk import XrayCore
from olcrtc.sdk import OlcRTC
from olcrtc.schemas import (
    ContainerConfigSchema,
    ContainerLogsSchema,
    ContainerSchema,
    ContainerStatsSchema,
)


class Containers:
    @staticmethod
    async def is_panel_container(cont: DockerContainer) -> bool:
        info = await cont.show()

        name = info["Name"].lstrip("/")
        parts = name.split("-", 2)

        return len(parts) == 3 and parts[0] == "olcwave"

    @staticmethod
    async def to_schema(cont: DockerContainer) -> ContainerSchema | None:
        info = await cont.show()

        name = info["Name"].lstrip("/")
        parts = name.split("-", 2)

        if len(parts) != 3:
            return None

        _, config_tag, user_id = parts

        return ContainerSchema(
            id=info["Id"][:12],
            name=name,
            short_uuid=user_id,
            config_tag=config_tag,
            status=info["State"]["Status"],
            created=info["Created"],
            image=info["Config"]["Image"],
        )

    @staticmethod
    async def all() -> list[ContainerSchema]:
        containers = await OlcRTC.all(include_stopped=True)

        schemas = await asyncio.gather(
            *(Containers.to_schema(container) for container in containers)
        )

        return [schema for schema in schemas if schema is not None]

    @staticmethod
    async def run(
        config: str,
        config_tag: str,
        short_uuid: str,
        name: str | None = None,
    ) -> None:
        routing_socks_addr = ""

        if await XrayCore.is_running():
            routing_socks_addr = "host.docker.internal:10808"

        await OlcRTC.run(
            config=config,
            config_tag=config_tag,
            user_id=short_uuid,
            upstream_proxy_addr=routing_socks_addr,
            name=name,
        )

    @staticmethod
    async def rename(old_name: str, new_name: str) -> None:
        await OlcRTC.rename(old_name, new_name)

    @staticmethod
    async def start(name: str) -> None:
        await OlcRTC.start(name)

    @staticmethod
    async def stop(name: str) -> None:
        await OlcRTC.stop(name)

    @staticmethod
    async def restart(
        name: str,
        upstream_proxy_addr: str = "",
        upstream_proxy_user: str = "",
        upstream_proxy_pass: str = "",
    ) -> None:
        await OlcRTC.restart(
            name=name,
            upstream_proxy_addr=upstream_proxy_addr,
            upstream_proxy_user=upstream_proxy_user,
            upstream_proxy_pass=upstream_proxy_pass,
        )

    @staticmethod
    async def remove(name: str) -> None:
        await OlcRTC.remove(name)

    @staticmethod
    async def logs(name: str, tail: int | None = None) -> ContainerLogsSchema:
        logs = await OlcRTC.logs(name, tail=tail)

        return ContainerLogsSchema(
            name=name,
            logs=logs,
        )

    @staticmethod
    async def get_config(name: str) -> ContainerConfigSchema:
        config = await OlcRTC.get_config(name)

        if isinstance(config, bytes):
            config = config.decode()

        return ContainerConfigSchema(
            name=name,
            config=config,
        )

    @staticmethod
    async def get_stats(name: str) -> ContainerStatsSchema:
        data = await OlcRTC.get_stats(name)

        return ContainerStatsSchema(
            name=name,
            upload_bytes=int(data.get("upload_bytes", 0)),
            download_bytes=int(data.get("download_bytes", 0)),
            total_bytes=int(data.get("total_bytes", 0)),
            upload_rate_bps=int(data.get("upload_rate_bps", 0)),
            download_rate_bps=int(data.get("download_rate_bps", 0)),
        )

    @staticmethod
    async def stop_all_by_short_uuid(short_uuid: str) -> None:
        containers = await Containers.all()

        await asyncio.gather(
            *(
                Containers.stop(container.name)
                for container in containers
                if container.short_uuid == short_uuid
            )
        )

    @staticmethod
    async def stop_all_by_config_tag(config_tag: str) -> None:
        containers = await Containers.all()

        await asyncio.gather(
            *(
                Containers.stop(container.name)
                for container in containers
                if container.config_tag == config_tag
            )
        )

    @staticmethod
    async def remove_all_by_short_uuid(short_uuid: str) -> None:
        containers = await Containers.all()

        await asyncio.gather(
            *(
                Containers.remove(container.name)
                for container in containers
                if container.short_uuid == short_uuid
            )
        )

    @staticmethod
    async def remove_all_by_config_tag(config_tag: str) -> None:
        containers = await Containers.all()

        await asyncio.gather(
            *(
                Containers.remove(container.name)
                for container in containers
                if container.config_tag == config_tag
            )
        )