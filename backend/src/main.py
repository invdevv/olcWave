# Copyright (C) 2026 invdevv - https://github.com/invdevv
# This file is part of olcwave.
# OLCWave is free software licensed under AGPL-3.0.

import asyncio

from aiodocker import DockerError
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import uvicorn

from routing.service import Routing
from settings.service import SettingsService
from settings.router import router as settings_router
from auth.router import router as auth_router
from profiles.router import router as configs_router
from profiles.vault_router import router as vault_router
from users.router import router as users_router
from subscriptions.router import router as subscriptions_router
from olcrtc.router import router as containers_router
from routing.router import router as routing_router
from xraycore.sdk import XrayCore
from config import settings
from database import create_tables
from traffic import TrafficManager
from room_rotator import RoomRotator
from rw_sync import SyncManager
from docker_client import init_docker, close_docker


async def lifespan(app: FastAPI):
    await create_tables()
    await init_docker()
    await SettingsService.load()

    try:
        routing = await Routing.get()
    except HTTPException:
        routing = False
    if routing:
        await XrayCore.run(routing)

    if settings.RW_ENABLED:
        SyncManager.start()

    traffic_task = asyncio.create_task(TrafficManager.run())
    rotator_task = asyncio.create_task(RoomRotator.run())

    yield

    traffic_task.cancel()
    try:
        await traffic_task
    except asyncio.CancelledError:
        pass

    rotator_task.cancel()
    try:
        await rotator_task
    except asyncio.CancelledError:
        pass

    if settings.RW_ENABLED:
        await SyncManager.stop()

    try:
        await XrayCore.stop()
    except DockerError:
        pass
    await close_docker()


app = FastAPI(lifespan=lifespan, openapi_url="", docs_url="", redoc_url="")  # pyright: ignore[reportArgumentType]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(configs_router)
app.include_router(vault_router)
app.include_router(users_router)
app.include_router(subscriptions_router)
app.include_router(containers_router)
app.include_router(settings_router)
app.include_router(routing_router)


@app.get("/health")
async def healthcheck():
    return "ok"


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0")
