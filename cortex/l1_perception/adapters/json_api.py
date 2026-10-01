"""Generic JSON API adapter: templated list request(s), optional per-item detail request, dotted-path items.

Config (``request`` / ``detail`` blocks in config/adapters/<key>.yaml):
  request: {method, url, json|params, items_path, id_path, vars: {name: [values…]}, page: {param, size, max_pages}}
  detail:  {method, url, json|params, root_path}      # "{id}" is substituted from the list item
"""

from __future__ import annotations

import itertools
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from cortex.l1_perception.adapters.base import FetchContext, register
from cortex.l1_perception.mapping import get_path
from cortex.l1_perception.models import RawItem
from platform_core import secrets

if TYPE_CHECKING:
    from cortex.l1_perception.registry import SourceConfig


def _fill(template: Any, values: dict[str, Any]) -> Any:
    """Substitute {name} placeholders in strings nested anywhere in a JSON-like structure."""
    if isinstance(template, str):
        if template.startswith("{") and template.endswith("}") and template[1:-1] in values:
            return values[template[1:-1]]  # whole-value placeholder keeps the type (int ids, lists)
        return template.format(**values) if "{" in template else template
    if isinstance(template, dict):
        return {k: _fill(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill(v, values) for v in template]
    return template


class JSONAPIAdapter:
    name = "json_api"
    version = "json_api-1.0"

    async def _call(
        self, ctx: FetchContext, spec: dict[str, Any], values: dict[str, Any], headers: dict[str, str]
    ) -> Any:
        kw: dict[str, Any] = {"headers": headers}
        if "json" in spec:
            kw["json"] = _fill(spec["json"], values)
        if "params" in spec:
            kw["params"] = _fill(spec["params"], values)
        r = await ctx.request(spec.get("method", "GET"), _fill(spec["url"], values), **kw)
        return r.json()

    async def fetch(self, cfg: SourceConfig, ctx: FetchContext) -> AsyncIterator[RawItem]:
        req = cfg.request or {}
        headers = {"Accept": "application/json"}
        if cfg.auth_ref:
            token = secrets.resolve(cfg.auth_ref)
            if token:
                headers[cfg.auth_header] = cfg.auth_scheme + token
        var_names = list((req.get("vars") or {}).keys())
        combos = itertools.product(*(req["vars"][n] for n in var_names)) if var_names else [()]
        page = req.get("page") or {}
        seen: set[str] = set()
        emitted = 0
        for combo in combos:
            values = dict(zip(var_names, combo, strict=True))
            for page_no in range(int(page.get("max_pages", 1))):
                if page:
                    values[page["param"]] = page_no * int(page.get("size", 1)) + int(page.get("start", 0))
                data = await self._call(ctx, req, values, headers)
                items = get_path(data, req["items_path"]) if req.get("items_path") else data
                if not isinstance(items, list) or not items:
                    break
                for item in items:
                    item_id = str(get_path(item, req.get("id_path", "id")))
                    if item_id in seen:
                        continue
                    seen.add(item_id)
                    payload = item
                    if cfg.detail:
                        detail = await self._call(ctx, cfg.detail, {**values, "id": item_id}, headers)
                        root = get_path(detail, cfg.detail["root_path"]) if cfg.detail.get("root_path") else detail
                        payload = {**item, **(root if isinstance(root, dict) else {"detail": root})}
                    payload = json.loads(json.dumps(payload, default=str))
                    yield RawItem(payload={"id": item_id, **payload}, url=str(req["url"]), fetched_at=datetime.now(UTC))
                    emitted += 1
                    if emitted >= ctx.max_items:
                        return


register(JSONAPIAdapter())
