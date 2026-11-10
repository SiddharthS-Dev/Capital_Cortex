"""Connection security for the migration and backup tools (ETL, MySQL backup/restore).

- Secrets come from an environment variable or a file named by ``<NAME>_FILE`` (Docker/Kubernetes secrets, a
  secret-manager mount). Passwords are never taken from command-line arguments, which end up in shell history and in
  every process listing.
- A remote server (anything but loopback) must use TLS **with certificate verification** by default. Weaker modes
  against a remote host are refused unless ``MIGRATION_ALLOW_UNVERIFIED_TLS=1`` is set explicitly.
- pymysql given an ``ssl`` dict without a CA encrypts but does not verify the server; this module therefore builds
  the ``ssl.SSLContext`` itself.
"""

from __future__ import annotations

import os
import ssl
from collections.abc import Mapping
from pathlib import Path
from typing import Any

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MYSQL_SSL_MODES = ("DISABLED", "REQUIRED", "VERIFY_CA", "VERIFY_IDENTITY")
PG_SSL_MODES = ("disable", "allow", "prefer", "require", "verify-ca", "verify-full")
ALLOW_UNVERIFIED_ENV = "MIGRATION_ALLOW_UNVERIFIED_TLS"


class InsecureConnectionError(ValueError):
    """A connection setting would expose credentials or data to an unverified remote endpoint."""


def is_local(host: str) -> bool:
    return host.strip().lower() in LOCAL_HOSTS


def read_secret(names: tuple[str, ...], env: Mapping[str, str] | None = None) -> str | None:
    """First non-empty value of NAME, else the contents of the file named by NAME_FILE, in ``names`` order."""
    env = os.environ if env is None else env
    for name in names:
        if env.get(name):
            return env[name]
        path = env.get(f"{name}_FILE")
        if path:
            value = Path(path).read_text(encoding="utf-8").strip()
            if value:
                return value
    return None


def resolve_password(
    names: tuple[str, ...],
    host: str,
    *,
    password_file: str | None = None,
    local_default: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Password from ``password_file``, then the env names (and their _FILE variants).

    ``local_default`` (a dev password) applies only to loopback hosts; a remote host without an explicit secret fails.
    """
    if password_file:
        value = Path(password_file).read_text(encoding="utf-8").strip()
        if not value:
            raise ValueError(f"password file {password_file} is empty")
        return value
    value = read_secret(names, env)
    if value:
        return value
    if local_default is not None and is_local(host):
        return local_default
    raise ValueError(f"no password for {host}: set one of {', '.join(names)} (or <NAME>_FILE)")


def _allow_unverified(env: Mapping[str, str] | None) -> bool:
    env = os.environ if env is None else env
    return env.get(ALLOW_UNVERIFIED_ENV, "") == "1"


def mysql_ssl_context(
    host: str,
    mode: str | None = None,
    *,
    ca: str | None = None,
    cert: str | None = None,
    key: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ssl.SSLContext | None:
    """TLS context for pymysql (``ssl=``), or None for a plaintext loopback connection.

    Default mode: DISABLED on loopback, VERIFY_IDENTITY otherwise. Without ``ca`` the system trust store is used.
    """
    mode = (mode or ("DISABLED" if is_local(host) else "VERIFY_IDENTITY")).upper()
    if mode not in MYSQL_SSL_MODES:
        raise ValueError(f"MySQL ssl mode must be one of {', '.join(MYSQL_SSL_MODES)}, got {mode!r}")
    if mode in ("DISABLED", "REQUIRED") and not is_local(host) and not _allow_unverified(env):
        raise InsecureConnectionError(
            f"MySQL ssl mode {mode} does not verify {host}; use VERIFY_IDENTITY (or VERIFY_CA) with a CA, "
            f"or set {ALLOW_UNVERIFIED_ENV}=1 to accept the risk explicitly"
        )
    if mode == "DISABLED":
        return None
    if mode == "REQUIRED":
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    else:
        ctx = ssl.create_default_context(cafile=ca)
        ctx.check_hostname = mode == "VERIFY_IDENTITY"
        ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if cert:
        ctx.load_cert_chain(cert, key)
    return ctx


def pg_ssl_options(
    host: str,
    sslmode: str | None = None,
    *,
    sslrootcert: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """libpq ssl keyword arguments for psycopg.connect.

    Loopback keeps libpq's own default unless a mode is given; a remote host defaults to verify-full.
    ``sslrootcert="system"`` (libpq 16+) uses the system trust store.
    """
    if sslmode is None and is_local(host):
        return {"sslrootcert": sslrootcert} if sslrootcert else {}
    mode = (sslmode or "verify-full").lower()
    if mode not in PG_SSL_MODES:
        raise ValueError(f"PostgreSQL sslmode must be one of {', '.join(PG_SSL_MODES)}, got {mode!r}")
    if mode not in ("verify-ca", "verify-full") and not is_local(host) and not _allow_unverified(env):
        raise InsecureConnectionError(
            f"PostgreSQL sslmode {mode} does not verify {host}; use verify-full with --pg-sslrootcert, "
            f"or set {ALLOW_UNVERIFIED_ENV}=1 to accept the risk explicitly"
        )
    opts: dict[str, Any] = {"sslmode": mode}
    if sslrootcert:
        opts["sslrootcert"] = sslrootcert
    return opts


def describe_tls(config: Mapping[str, Any]) -> str:
    """Log-safe description of a connection's TLS (never includes secrets)."""
    if "ssl" in config and isinstance(config["ssl"], ssl.SSLContext):
        ctx = config["ssl"]
        if ctx.verify_mode == ssl.CERT_NONE:
            return "TLS (unverified)"
        return "TLS (verify identity)" if ctx.check_hostname else "TLS (verify CA)"
    if "sslmode" in config:
        return f"sslmode={config['sslmode']}"
    return "plaintext (loopback)"
