from fastapi import APIRouter, Depends, HTTPException, status

from auth.dependencies import get_current_admin
from xraycore.sdk import XrayCore
from olcrtc.schemas import ContainerSchema, ContainerConfigSchema, ContainerLogsSchema, ContainerStatsSchema
from olcrtc.service import Containers
from users.service import Users

router = APIRouter(prefix="/containers", tags=["containers"])

@router.get("/all")
async def get_all(_admin: dict = Depends(get_current_admin)) -> list[ContainerSchema]:
    return await Containers.all()

@router.post("/run")
async def run(name: str, _admin: dict = Depends(get_current_admin)):
    # Block starting a container when its owner has exceeded their traffic limit.
    # maxsplit=2: Remnawave shortUuid contains hyphens
    parts = name.split("-", 2)
    if len(parts) == 3 and parts[0] == "olcwave":
        try:
            traffic = await Users.get_traffic(parts[2])
        except Exception:
            traffic = None
        if traffic and traffic.exceeded:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="traffic_limit_exceeded",
            )

    await Containers.start(name)

    return "ok"

@router.post("/stop")
async def stop(name: str, _admin: dict = Depends(get_current_admin)):
    await Containers.stop(name)

    return "ok"

@router.post("/restart")
async def restart(name: str, _admin: dict = Depends(get_current_admin)):
    if await XrayCore.is_running():
        await Containers.restart(name, "host.docker.internal:10808")
    else:
        await Containers.restart(name)

    return "ok"

@router.delete("/")
async def remove(name: str, _admin: dict = Depends(get_current_admin)):
    await Containers.remove(name)

    return "ok"

@router.get("/logs")
async def logs(name: str, _admin: dict = Depends(get_current_admin)) -> ContainerLogsSchema:
    return await Containers.logs(name)

@router.get("/config")
async def get_config(name: str, _admin: dict = Depends(get_current_admin)) -> ContainerConfigSchema:
    return await Containers.get_config(name)

@router.get("/stats")
async def get_stats(name: str, _admin: dict = Depends(get_current_admin)) -> ContainerStatsSchema:
    return await Containers.get_stats(name)
