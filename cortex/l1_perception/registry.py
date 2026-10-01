"""Adapter registry: ``config/adapters/*.yaml`` → ``source`` rows. Adding a source is config, not code."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.config import get_settings


class SourceConfig(BaseModel):
    key: str
    name: str
    kind: str  # api | rss | html | file | manual | internal
    adapter: str  # json_api | rss | tabular | manual
    enabled: bool = False
    schedule: str | None = None  # crontab, UTC
    terms_note: str
    urls: list[str] = Field(default_factory=list)
    request: dict[str, Any] | None = None
    detail: dict[str, Any] | None = None
    auth_ref: str | None = None
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer "
    rate_limit: dict[str, float] = Field(default_factory=lambda: {"min_interval_seconds": 1.0})
    respect_robots: bool = True
    max_items: int = 500
    case_insensitive_keys: bool = False
    mapping: dict[str, Any] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)

    def config_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True, default=str).encode()).hexdigest()


def load_configs(directory: Path | None = None) -> dict[str, SourceConfig]:
    d = directory or (get_settings().config_dir / "adapters")
    out: dict[str, SourceConfig] = {}
    for f in sorted(d.glob("*.yaml")):
        cfg = SourceConfig(**yaml.safe_load(f.read_text(encoding="utf-8")))
        if cfg.key in out:
            raise ValueError(f"duplicate adapter key {cfg.key} in {f}")
        out[cfg.key] = cfg
    return out


async def sync_sources(session: AsyncSession) -> dict[str, str]:
    """Upsert one ``source`` row per config. ``enabled`` is set from config only on first insert; after that
    the UI toggle is authoritative. Returns key → source id."""
    org = get_settings().org_id
    ids: dict[str, str] = {}
    for cfg in load_configs().values():
        row = (
            await session.execute(
                text(
                    "INSERT INTO source (org_id, name, kind, adapter_key, adapter, schedule, config, terms_note, enabled, "
                    "config_hash, health) VALUES (:org, :name, :kind, :key, :adapter, :schedule, CAST(:config AS jsonb), "
                    ":terms, :enabled, :hash, CASE WHEN :enabled THEN 'unknown' ELSE 'disabled' END) "
                    "ON CONFLICT (org_id, adapter_key) DO UPDATE SET name = EXCLUDED.name, kind = EXCLUDED.kind, "
                    "adapter = EXCLUDED.adapter, schedule = EXCLUDED.schedule, config = EXCLUDED.config, "
                    "terms_note = EXCLUDED.terms_note, config_hash = EXCLUDED.config_hash RETURNING id"
                ),
                {
                    "org": org,
                    "name": cfg.name,
                    "kind": cfg.kind,
                    "key": cfg.key,
                    "adapter": cfg.adapter,
                    "schedule": cfg.schedule,
                    "config": json.dumps(cfg.model_dump(), default=str),
                    "terms": cfg.terms_note,
                    "enabled": cfg.enabled,
                    "hash": cfg.config_hash(),
                },
            )
        ).scalar_one()
        ids[cfg.key] = str(row)
    return ids


async def get_source(session: AsyncSession, source_id: str) -> tuple[dict[str, Any], SourceConfig]:
    row = (
        (
            await session.execute(
                text("SELECT * FROM source WHERE id = :id AND org_id = :org"),
                {"id": source_id, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        from platform_core.errors import NotFound

        raise NotFound("source not found")
    return dict(row), SourceConfig(**row["config"])
