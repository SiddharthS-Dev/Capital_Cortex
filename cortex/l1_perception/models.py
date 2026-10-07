"""L1 data contracts: raw items fetched by adapters, and the normalised ``Signal``."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class RawItem(BaseModel):
    """One record as the source returned it, plus where it came from."""

    payload: dict[str, Any]
    url: str | None = None
    fetched_at: datetime


class Signal(BaseModel):
    """Normalised signal. Every populated field is traceable through ``field_sources`` (I1/I5)."""

    source_key: str
    external_id: str | None = None
    title: str
    description: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    open_date: datetime | None = None
    deadline: datetime | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    currency: str | None = None
    countries: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    instruments: list[str] = Field(default_factory=list)
    stage_fit: list[str] = Field(default_factory=list)
    counterparty_name: str | None = None
    counterparty_kind: str | None = None
    counterparty_country: str | None = None
    counterparty_domain: str | None = None
    investor_type: str | None = None
    class_hint: str | None = None
    eligibility: dict[str, Any] = Field(default_factory=dict)
    # source-specific facts carried through untouched (mapped ``attr_<key>`` fields, e.g. outreach research);
    # values keep their type (number, date, text) and each key has provenance under ``attributes.<key>``
    attributes: dict[str, Any] = Field(default_factory=dict)
    # field → how it was obtained, e.g. {"deadline": "raw:synopsis.responseDate", "countries": "source_default"}
    field_sources: dict[str, str] = Field(default_factory=dict)

    @property
    def external_key(self) -> str | None:
        return f"{self.source_key}:{self.external_id}" if self.external_id else None

    def content_hash(self) -> str:
        """Hash of the normalised content: a revised listing is a new signal, a re-fetch of the same one isn't."""
        # empty ``attributes`` is left out so signals from sources without attr_ fields keep their existing hashes
        body = self.model_dump(mode="json", exclude={"field_sources", *(() if self.attributes else ("attributes",))})
        blob = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(blob.encode()).hexdigest()
