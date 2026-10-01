"""Shared API helpers: cursor pagination, row serialisation."""

from __future__ import annotations

import base64
import json

from platform_core.jsonutil import jsonable, row


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return int(json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))["o"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return 0


__all__ = ["decode_cursor", "encode_cursor", "jsonable", "row"]
