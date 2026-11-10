"""Phase 0 end-to-end smoke test against a running stack (`make up` first).

  1. Real OIDC login (authorization code + PKCE) for the dev-only `smoke-auditor`: password, then TOTP
  2. The token carries MFA evidence (amr), and the API accepts it for an MFA-required role
  3. GET /v1/audit/verify -> ok
  4. Service-account token -> POST /v1/system/ping -> the worker handles the job (bus round trip)
  5. Grafana (Tempo datasource) returns traces for the API

Usage: python scripts/smoke.py   (env overrides: API, KEYCLOAK, GRAFANA, SMOKE_USER)
Credentials come from the environment or the git-ignored .env, never from this file (SEC-1): SMOKE_USER_PASSWORD,
SMOKE_TOTP_SECRET (smoke-auditor's TOTP seed), WORKER_CLIENT_SECRET, and GRAFANA_PASSWORD or GRAFANA_ADMIN_PASSWORD
for the Grafana step. A missing one stops the run with a message naming it; values are never printed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import struct
import sys
import tempfile
import time
from pathlib import Path
from typing import Literal, overload
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx

API = os.environ.get("API", "http://localhost:8300")
KC = os.environ.get("KEYCLOAK", "http://localhost:8380")
GRAFANA = os.environ.get("GRAFANA", "http://localhost:3301")
REALM = f"{KC}/realms/cortex"
REDIRECT = "http://localhost:3300/auth/callback"
USER = os.environ.get("SMOKE_USER", "smoke-auditor")
WORKER_ID = "cortex-worker"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

ok_count = 0


@overload
def setting(name: str, *, required: Literal[True] = ...) -> str: ...
@overload
def setting(name: str, *, required: bool) -> str | None: ...
def setting(name: str, *, required: bool = True) -> str | None:
    """A credential from the environment, else the git-ignored .env. No committed fallback: a required one that is
    missing stops the run with a clear message. Values are never printed."""
    v = os.environ.get(name)
    if not v and ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            key, sep, val = line.partition("=")
            if sep and key.strip() == name and val.strip():
                v = val.strip().strip('"')
                break
    if not v and required:
        raise SystemExit(f"smoke: set {name} in the environment or .env (no credential is committed in this script)")
    return v


def step(msg: str, cond: bool, detail: str = "") -> None:
    global ok_count
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}" + (f" - {detail}" if detail else ""))
    if not cond:
        sys.exit(1)
    ok_count += 1


def totp(secret: bytes, t: float | None = None, step_s: int = 30, digits: int = 6) -> str:
    counter = int((t or time.time()) // step_s)
    mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[o : o + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return str(code).zfill(digits)


def form_action(page: str) -> str:
    m = re.search(r'<form[^>]+action="([^"]+)"', page)
    if not m:
        raise RuntimeError("no form on page:\n" + page[:500])
    return html.unescape(m.group(1))


def claims(tok: str) -> dict:
    part = tok.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def browser_login(c: httpx.Client) -> str:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    q = {
        "client_id": "cortex-web",
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": REDIRECT,
        "state": secrets.token_hex(8),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    r = c.get(f"{REALM}/protocol/openid-connect/auth?{urlencode(q)}")
    r = c.post(
        form_action(r.text), data={"username": USER, "password": setting("SMOKE_USER_PASSWORD"), "credentialId": ""}
    )
    step("password accepted; OTP form presented", "otp" in r.text.lower() and r.status_code == 200)
    # Keycloak rejects a TOTP code that was already used (replay protection); never reuse a 30 s window.
    stamp = Path(tempfile.gettempdir()) / "cortex-smoke-totp-window"
    window = int(time.time() // 30)
    if stamp.exists() and stamp.read_text().strip() == str(window):
        time.sleep(30 - time.time() % 30 + 1)
    stamp.write_text(str(int(time.time() // 30)))
    sel = re.search(r'name="selectedCredentialId" value="([^"]+)"', r.text)
    r = c.post(
        form_action(r.text),
        data={
            "otp": totp(setting("SMOKE_TOTP_SECRET").encode()),
            "login": "Sign In",
            "selectedCredentialId": sel.group(1) if sel else "",
        },
    )
    loc = r.headers.get("location", "")
    step(
        "TOTP accepted; redirected with authorization code",
        r.status_code == 302 and "code=" in loc,
        f"status={r.status_code} location={loc[:160]}",
    )
    code = parse_qs(urlparse(loc).query)["code"][0]
    t = c.post(
        f"{REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": "cortex-web",
            "code_verifier": verifier,
        },
    )
    t.raise_for_status()
    return t.json()["access_token"]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"Capital Cortex smoke - API {API}, IdP {KC}")
    for name in ("SMOKE_USER_PASSWORD", "SMOKE_TOTP_SECRET", "WORKER_CLIENT_SECRET"):  # fail before any request
        setting(name)
    with httpx.Client(follow_redirects=False, timeout=20) as c:
        # Keycloak marks its cookies Secure; browsers send those to http://localhost, Python's cookie jar
        # does not, so this dev-only script clears the flag.
        def _insecure_cookies(_resp: httpx.Response) -> None:
            _resp.read()
            for ck in c.cookies.jar:
                ck.secure = False

        c.event_hooks["response"] = [_insecure_cookies]
        # redirects inside Keycloak are followed manually so the final code redirect can be captured
        orig_get = c.get

        def get(url, **kw):
            r = orig_get(url, **kw)
            while r.status_code in (302, 303) and REDIRECT not in r.headers.get("location", ""):
                r = orig_get(urljoin(url, r.headers["location"]))
            return r

        c.get = get  # type: ignore[method-assign]
        token = browser_login(c)

    cl = claims(token)
    step(
        "access token has MFA evidence",
        "otp" in (cl.get("amr") or []) or cl.get("acr") in ("mfa", "2"),
        f"amr={cl.get('amr')} acr={cl.get('acr')}",
    )
    step(
        "audience includes cortex-api",
        "cortex-api" in (cl.get("aud") if isinstance(cl.get("aud"), list) else [cl.get("aud")]),
    )
    h = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=API, timeout=30) as api:
        me = api.get("/v1/me", headers=h)
        step(
            "GET /v1/me as auditor (MFA-required role)",
            me.status_code == 200 and me.json()["mfa"],
            f"roles={me.json().get('roles') if me.status_code == 200 else me.text[:200]}",
        )
        v = api.get("/v1/audit/verify", headers=h)
        step("GET /v1/audit/verify returns ok", v.status_code == 200 and v.json()["ok"] is True, v.text[:200])
        denied = api.post("/v1/system/ping", headers=h)
        step("auditor is denied system:ping (403)", denied.status_code == 403)

        svc = httpx.post(
            f"{REALM}/protocol/openid-connect/token",
            data={"grant_type": "client_credentials"},
            auth=(WORKER_ID, setting("WORKER_CLIENT_SECRET")),
            timeout=10,
        )
        svc.raise_for_status()
        sh = {"Authorization": f"Bearer {svc.json()['access_token']}"}
        p = api.post("/v1/system/ping", headers=sh)
        step("service account POST /v1/system/ping accepted", p.status_code == 202, p.text[:200])
        env_id = p.json()["envelope_id"]
        done = None
        for _ in range(30):
            done = api.get(f"/v1/system/ping/{env_id}", headers=sh).json()
            if done["done"]:
                break
            time.sleep(1)
        step(
            "worker handled the job (bus -> worker -> audit)",
            bool(done and done["done"]),
            f"handled_by={done and done.get('handled_by')}",
        )
        v2 = api.get("/v1/audit/verify", headers=h).json()
        step(
            "audit chain still verifies after new records",
            v2["ok"] and v2["checked"] >= 3,
            f"checked={v2['checked']} head={str(v2['head_hash'])[:12]}...",
        )

    # Traces need the observability stack (Grafana + Tempo), which the MySQL demo stack does not run. When Grafana is
    # unreachable, or excluded on purpose (SMOKE_SKIP_TRACES=1), the check is reported as SKIPPED with the reason and is
    # never counted as passed. When Grafana is reachable, the check runs and can fail as before.
    skip_reason = None
    if os.environ.get("SMOKE_SKIP_TRACES") == "1":
        skip_reason = "SMOKE_SKIP_TRACES=1 (observability excluded on purpose)"
    else:
        try:
            httpx.get(f"{GRAFANA}/api/health", timeout=5)
        except httpx.HTTPError as e:
            skip_reason = (
                f"Grafana unreachable at {GRAFANA} ({type(e).__name__}); observability is not part of this stack"
            )
    if skip_reason:
        print(f"  [SKIP] Grafana shows API traces from Tempo - SKIPPED: {skip_reason}")
        print()
        print(f"SMOKE OK - {ok_count} checks passed, 1 skipped (traces: {skip_reason})")
        return

    found = 0
    for _ in range(20):
        g = httpx.get(
            f"{GRAFANA}/api/datasources/proxy/uid/tempo/api/search",
            params={"tags": "service.name=capital-cortex-api", "limit": 5},
            auth=("admin", setting("GRAFANA_PASSWORD", required=False) or setting("GRAFANA_ADMIN_PASSWORD")),
            timeout=10,
        )
        if g.status_code == 200:
            found = len(g.json().get("traces", []))
            if found:
                break
        time.sleep(3)
    step("Grafana shows API traces from Tempo", found > 0, f"traces={found}")
    print(f"\nSMOKE OK - {ok_count} checks passed")


if __name__ == "__main__":
    main()
