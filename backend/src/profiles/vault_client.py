"""Client for the auth-token vault sidecar (self-refreshing Yandex Session_id).

Config from env VAULT_URL / VAULT_SECRET, falling back to a JSON file
/app/vault.json ({"url": ..., "secret": ...}) so it can be dropped in without
recreating the container. When no URL is configured the vault is simply off and
every call is a no-op (managed tokens are only used by profiles that opt in).
"""
import json
import os

import httpx

_CONF_FILE = "/app/vault.json"


def _conf() -> tuple[str | None, str]:
    url = os.environ.get("VAULT_URL")
    secret = os.environ.get("VAULT_SECRET", "")
    if not url:
        try:
            d = json.load(open(_CONF_FILE))
            url = d.get("url")
            secret = d.get("secret", "")
        except Exception:
            url = None
    return url, secret


class Vault:
    @staticmethod
    def configured() -> bool:
        return bool(_conf()[0])

    @staticmethod
    async def request(method: str, path: str, params: dict | None = None) -> tuple[int, dict]:
        """Raw proxied call to the vault. Returns (status_code, json_body). Used by
        the panel-facing router so it can pass the vault's status/errors through."""
        url, secret = _conf()
        if not url:
            return 503, {"error": "vault not configured"}
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                res = await client.request(
                    method, f"{url}{path}", params=params or {},
                    headers={"X-Vault-Secret": secret},
                )
            try:
                body = res.json()
            except Exception:
                body = {"raw": res.text[:300]}
            return res.status_code, body
        except Exception as exc:
            return 502, {"error": str(exc)}

    @staticmethod
    async def get_token(account: str) -> str | None:
        """Current fresh Session_id for `account`, or None if unavailable/dead.
        The vault spins up a browser on demand for this (heavy)."""
        if not account:
            return None
        code, body = await Vault.request("GET", "/token", {"account": account})
        if code == 200:
            tok = body.get("token")
            return tok if isinstance(tok, str) and tok.strip() else None
        return None
