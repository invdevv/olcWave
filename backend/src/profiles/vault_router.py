"""Panel-facing proxy to the auth-token vault sidecar.

The panel never talks to the vault directly (nor holds its secret): it calls
these admin-authed endpoints, and olcWave forwards to the vault server-side. The
noVNC stream itself is proxied separately by nginx (a websocket), not here.
"""
import json

from fastapi import APIRouter, Depends, Response

from auth.dependencies import get_current_admin
from profiles.vault_client import Vault

router = APIRouter(prefix="/vault", tags=["vault"])


def _resp(code: int, body: dict) -> Response:
    return Response(content=json.dumps(body), status_code=code, media_type="application/json")


@router.get("/accounts")
async def accounts(_admin: dict = Depends(get_current_admin)):
    code, body = await Vault.request("GET", "/accounts")
    return _resp(code, body)


@router.post("/login/start")
async def login_start(account: str | None = None, _admin: dict = Depends(get_current_admin)):
    params = {"account": account} if account else None
    code, body = await Vault.request("POST", "/login/start", params)
    return _resp(code, body)


@router.post("/login/commit")
async def login_commit(_admin: dict = Depends(get_current_admin)):
    code, body = await Vault.request("POST", "/login/commit")
    if code == 200:
        account = body.get("account")
        # Also hand back the fresh Session_id so the panel can build the managed
        # token entry {token, account} for the profile it is editing.
        body["token"] = await Vault.get_token(account) if account else None
    return _resp(code, body)


@router.post("/login/cancel")
async def login_cancel(_admin: dict = Depends(get_current_admin)):
    code, body = await Vault.request("POST", "/login/cancel")
    return _resp(code, body)


@router.get("/login/status")
async def login_status(_admin: dict = Depends(get_current_admin)):
    # Panel polls this to auto-detect when the user has finished signing in.
    code, body = await Vault.request("GET", "/login/status")
    return _resp(code, body)
