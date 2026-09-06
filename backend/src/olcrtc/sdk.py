import json

import yaml
from aiodocker import DockerError
from aiodocker.containers import DockerContainer

import docker_client


class OlcRTC:
    @staticmethod
    async def build(rebuild: bool = False):
        docker = docker_client.docker
        if not rebuild:
            try:
                _=await docker.images.get("olcrtc")
                return
            except DockerError:
                pass

        _= await docker.images.build(
            path_dockerfile="olcrtc",
            tag="olcrtc",
            rm=True,
            forcerm=True
        )

    @staticmethod
    async def run(
        config: str,
        config_tag: str,
        user_id: str,
        upstream_proxy_addr: str = "",
        upstream_proxy_user: str = "",
        upstream_proxy_pass: str = "",
        name: str | None = None,
    ):
        docker = docker_client.docker
        if name is None:
            name = f"olcwave-{config_tag}-{user_id}"

        try:
            old = await docker.containers.get(name)
            await old.delete(force=True)
        except DockerError:
            pass

        container = await docker.containers.create(
            config={
                "Image": "olcrtc",
                "Env": [
                    f"CONFIG={config}",
                    f"UPSTREAM_SOCKS={upstream_proxy_addr}",
                    f"UPSTREAM_USER={upstream_proxy_user}",
                    f"UPSTREAM_PASS={upstream_proxy_pass}",
                ],
                "HostConfig": {
                    "ExtraHosts": [
                        "host.docker.internal:host-gateway",
                    ]
                },
            },
            name=name,
        )

        await container.start()

        return container

    @staticmethod
    async def start(name: str):
        docker = docker_client.docker
        container = await docker.containers.get(name)
        await container.start()


    @staticmethod
    async def stop(name: str):
        docker = docker_client.docker
        container = await docker.containers.get(name)
        await container.stop()

    @staticmethod
    async def restart(
        name: str,
        upstream_proxy_addr: str = "",
        upstream_proxy_user: str = "",
        upstream_proxy_pass: str = "",
    ):
        docker = docker_client.docker
        container = await docker.containers.get(name)

        info = await container.show()

        image = info["Config"]["Image"]

        env = {}
        for item in info["Config"].get("Env", []):
            if "=" in item:
                k, v = item.split("=", 1)
                env[k] = v

        env["UPSTREAM_SOCKS"] = upstream_proxy_addr
        env["UPSTREAM_USER"] = upstream_proxy_user
        env["UPSTREAM_PASS"] = upstream_proxy_pass

        if "CONFIG" in env:
            try:
                cfg = yaml.safe_load(env["CONFIG"])
                if isinstance(cfg, dict):
                    cfg.pop("data", None)
                    env["CONFIG"] = yaml.dump(cfg)
            except yaml.YAMLError:
                pass

        state = info["State"]["Status"]

        if state == "running":
            await container.delete(force=True)

        new_container = await docker.containers.create(
            config={
                "Image": image,
                "Env": [f"{k}={v}" for k, v in env.items()],
                "HostConfig": {
                    "ExtraHosts": [
                        "host.docker.internal:host-gateway",
                    ]
                },
            },
            name=name,
        )

        await new_container.start()

    @staticmethod
    async def remove(name: str):
        docker = docker_client.docker
        container = await docker.containers.get(name)
        await container.delete(force=True)

    @staticmethod
    async def rename(old_name: str, new_name: str):
        docker = docker_client.docker
        container = await docker.containers.get(old_name)
        await container.rename(new_name)

    @staticmethod
    async def logs(name: str, tail: int | None = None) -> str:
        docker = docker_client.docker
        container = await docker.containers.get(name)
        kwargs = {"stdout": True, "stderr": True}
        if tail is not None:
            kwargs["tail"] = tail
        logs = await container.log(**kwargs)
        return "".join(logs)

    @staticmethod
    async def get(name: str) -> DockerContainer:
        docker = docker_client.docker
        return await docker.containers.get(name)

    @staticmethod
    async def all(include_stopped: bool = False) -> list[DockerContainer]:
        docker = docker_client.docker
        return await docker.containers.list(all=include_stopped)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

    @staticmethod
    async def get_config(name: str):
        docker = docker_client.docker
        container = await docker.containers.get(name)

        exec_ = await container.exec(cmd=["cat", "/tmp/olcwave/config.yaml"])
        stream = exec_.start(detach=False)
        config = await stream.read_out()
        return config.data.decode().strip()

    @staticmethod
    async def get_stats(name: str) -> dict:  # pyright: ignore[reportUnknownParameterType]
        docker = docker_client.docker
        container = await docker.containers.get(name)

        exec_ = await container.exec(
            cmd=["cat", "/tmp/olcwave/stats.json"]
        )
        stream = exec_.start(detach=False)
        result = await stream.read_out()

        raw = result.data.decode().strip()

        if not raw:
            return {}

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}

        return data if isinstance(data, dict) else {}