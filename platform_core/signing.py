"""Content hashing and signed approval tokens (I3).

An approval token is a short-lived HS256 JWT bound to one subject and the SHA-256 of its canonical content:
``{sub: "<type>:<id>", content_hash, approver, approvers[], jti, iat, exp, iss, aud}``. Whoever releases the
subject re-hashes the content it is about to deliver and compares it with the token, so an edit made after
approval can't be delivered under the old approval. The key comes from a secret ref (``env:`` or ``vault:``).
There is no default key: without one, approvals fail closed.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt

from platform_core import secrets
from platform_core.config import get_settings

ISSUER = "cortex-approval-service"
AUDIENCE = "cortex-outbox"
MIN_KEY_BYTES = 32


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(obj: Any) -> str:
    """SHA-256 of the canonical JSON form. Key order and whitespace never change the hash."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


class SigningKeyMissing(RuntimeError):
    """No usable approval signing key is configured, so approvals fail closed."""


class InvalidApprovalToken(Exception):
    permanent = True


@dataclass(frozen=True)
class IssuedToken:
    token: str
    jti: str
    expires_at: int


class ApprovalTokenSigner:
    def __init__(self, key: bytes, ttl_seconds: int = 24 * 3600) -> None:
        if len(key) < MIN_KEY_BYTES:
            raise SigningKeyMissing(f"approval signing key must be at least {MIN_KEY_BYTES} bytes")
        self._key = key
        self.ttl = ttl_seconds

    @classmethod
    def from_settings(cls) -> ApprovalTokenSigner:
        s = get_settings()
        raw = secrets.resolve(s.approval_signing_key_ref)
        if not raw:
            raise SigningKeyMissing(f"approval signing key not configured ({s.approval_signing_key_ref})")
        return cls(raw.encode("utf-8"), s.approval_token_ttl_seconds)

    def issue(self, subject: str, digest: str, approver: str, approvers: list[str], **extra: Any) -> IssuedToken:
        now = int(time.time())
        jti = str(uuid.uuid4())
        exp = now + self.ttl
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": subject,
            "content_hash": digest,
            "approver": approver,
            "approvers": approvers,
            "jti": jti,
            "iat": now,
            "exp": exp,
            **extra,
        }
        return IssuedToken(jwt.encode(claims, self._key, algorithm="HS256"), jti, exp)

    def verify(self, token: str, *, subject: str, digest: str) -> dict[str, Any]:
        """Checks the signature, expiry, issuer/audience, subject binding and content hash."""
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=["HS256"],
                audience=AUDIENCE,
                issuer=ISSUER,
                options={"require": ["exp", "iat", "jti", "sub", "content_hash"]},
            )
        except jwt.InvalidTokenError as e:
            raise InvalidApprovalToken(f"approval token invalid: {e}") from e
        if claims["sub"] != subject:
            raise InvalidApprovalToken("approval token is bound to a different subject")
        if claims["content_hash"] != digest:
            raise InvalidApprovalToken("content changed after approval (hash mismatch)")
        return claims
