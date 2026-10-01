"""The §8 API surface for endpoints whose modules arrive in later phases.

Each route is registered now, so the OpenAPI contract, the authz matrix and the UI wiring are stable from
Phase 0. Each route authenticates and authorises exactly as its real version will, then raises
``NotImplementedError("PHASE-n: …")``, which becomes a 501 "Coming in Phase n". None of them returns fake
data (working rule 2). When a phase ships an endpoint, delete its row here and add the real router.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Path

from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.errors import ProblemDoc


@dataclass(frozen=True)
class Planned:
    method: str
    path: str
    permission: str
    resource: str
    phase: int
    summary: str
    tag: str
    step_up: bool = False


# Every §8 endpoint has shipped (Phase 3). The mechanism stays for future extension points.
PLANNED: list[Planned] = []


def _make_handler(pl: Planned):
    async def handler(**_: object):
        raise NotImplementedError(f"PHASE-{pl.phase}: {pl.method} /v1{pl.path} — {pl.summary}")

    # Declare the path parameters and the authz dependency explicitly, so OpenAPI documents them.
    params = [
        inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=str, default=Path(...))
        for name in re.findall(r"{(\w+)}", pl.path)
    ]
    params.append(
        inspect.Parameter(
            "principal",
            inspect.Parameter.KEYWORD_ONLY,
            annotation=Principal,
            default=Depends(authorize(pl.permission, pl.resource, step_up=pl.step_up)),
        )
    )
    handler.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    handler.__name__ = "planned_" + re.sub(r"\W+", "_", f"{pl.method}_{pl.path}").strip("_").lower()
    return handler


def build_router() -> APIRouter:
    router = APIRouter(prefix="/v1")
    for pl in PLANNED:
        router.add_api_route(
            pl.path,
            _make_handler(pl),
            methods=[pl.method],
            summary=f"{pl.summary} [Phase {pl.phase}]",
            tags=[pl.tag],
            responses={
                501: {
                    "description": f"Coming in Phase {pl.phase}",
                    "model": ProblemDoc,
                    "content": {"application/problem+json": {}},
                }
            },
            openapi_extra={"x-cortex-phase": pl.phase, "x-cortex-permission": pl.permission},
        )
    return router
