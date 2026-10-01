"""CSV/XLSX upload adapter (investor lists, CRM exports, opportunity lists). Rows become raw items keyed by header."""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from cortex.l1_perception.adapters.base import FetchContext, register
from cortex.l1_perception.models import RawItem

if TYPE_CHECKING:
    from cortex.l1_perception.registry import SourceConfig


def read_rows(data: bytes, filename: str) -> list[dict[str, Any]]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        header = [str(h).strip() if h is not None else f"col{i}" for i, h in enumerate(rows[0])]
        out = []
        for r in rows[1:]:
            if all(v in (None, "") for v in r):
                continue
            out.append(
                {
                    header[i]: (v.isoformat() if isinstance(v, datetime) else v)
                    for i, v in enumerate(r)
                    if i < len(header)
                }
            )
        return out
    text = data.decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t") if text.strip() else csv.excel
    return [
        {(k or "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        for row in csv.DictReader(io.StringIO(text), dialect=dialect)
        if any((v or "").strip() for v in row.values() if isinstance(v, str))
    ]


class TabularAdapter:
    name = "tabular"
    version = "tabular-1.0"

    async def fetch(self, cfg: SourceConfig, ctx: FetchContext) -> AsyncIterator[RawItem]:
        if ctx.upload is None:
            raise ValueError("tabular sources ingest uploaded files; use POST /v1/sources/{id}/upload")
        for n, row in enumerate(read_rows(ctx.upload, ctx.upload_name or "upload.csv")):
            if n >= ctx.max_items:
                break
            yield RawItem(
                payload={"_row": n + 2, "_file": ctx.upload_name, **row},
                url=f"upload://{ctx.upload_name}#row={n + 2}",
                fetched_at=datetime.now(UTC),
            )


register(TabularAdapter())
