"""JSON-safe conversion of DB rows (UUID, datetime, Decimal) shared by every layer."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def jsonable(v: Any) -> Any:
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [jsonable(x) for x in v]
    return v


def row(r: Any) -> dict[str, Any]:
    return {k: jsonable(v) for k, v in dict(r).items()}
