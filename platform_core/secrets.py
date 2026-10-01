"""Secret references: ``env:NAME`` or ``vault:<kv-v2 path>#<key>``. Secrets never live in committed files."""

from __future__ import annotations

import os
from functools import lru_cache

import httpx

from platform_core.config import get_settings


class SecretError(RuntimeError):
    pass


@lru_cache(maxsize=128)
def _vault_read(path: str) -> dict[str, str]:
    s = get_settings()
    token = os.environ.get("VAULT_TOKEN")
    if not token:
        raise SecretError("VAULT_TOKEN not set")
    mount, _, rest = path.partition("/")
    r = httpx.get(f"{s.vault_addr.rstrip('/')}/v1/{mount}/data/{rest}", headers={"X-Vault-Token": token}, timeout=5)
    if r.status_code != 200:
        raise SecretError(f"vault read {path} failed: HTTP {r.status_code}")
    return r.json()["data"]["data"]


def resolve(ref: str | None) -> str | None:
    if not ref:
        return None
    kind, _, spec = ref.partition(":")
    if kind == "env":
        return os.environ.get(spec)
    if kind == "vault":
        path, _, key = spec.partition("#")
        return _vault_read(path).get(key)
    raise SecretError(f"unsupported secret ref {ref!r}")
