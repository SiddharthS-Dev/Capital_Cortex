"""Dev helper: print an access token for a realm user via the real browser login flow (auth code + PKCE).

Usage: python scripts/devtoken.py <username> <password> [totp_secret]
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from smoke import REALM, REDIRECT, form_action, totp


def token(username: str, password: str, otp_secret: str | None = None) -> str:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    c = httpx.Client(follow_redirects=False, timeout=20)

    def _cookies(r: httpx.Response) -> None:
        r.read()
        for ck in c.cookies.jar:
            ck.secure = False

    c.event_hooks["response"] = [_cookies]
    q = {
        "client_id": "cortex-web",
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": REDIRECT,
        "state": "dev",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    r = c.get(f"{REALM}/protocol/openid-connect/auth?{urlencode(q)}")
    r = c.post(form_action(r.text), data={"username": username, "password": password, "credentialId": ""})
    if otp_secret and r.status_code == 200:
        sel = re.search(r'name="selectedCredentialId" value="([^"]+)"', r.text)
        r = c.post(
            form_action(r.text),
            data={
                "otp": totp(otp_secret.encode()),
                "login": "Sign In",
                "selectedCredentialId": sel.group(1) if sel else "",
            },
        )
    loc = r.headers.get("location", "")
    if not loc.startswith(REDIRECT):
        raise SystemExit(f"login did not complete (status {r.status_code}); MFA enrolment or bad credentials?")
    code = parse_qs(urlparse(loc).query)["code"][0]
    t = httpx.post(
        f"{REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": "cortex-web",
            "code_verifier": verifier,
        },
        timeout=20,
    )
    t.raise_for_status()
    return t.json()["access_token"]


if __name__ == "__main__":
    print(token(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
