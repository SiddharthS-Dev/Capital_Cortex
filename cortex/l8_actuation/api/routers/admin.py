"""Admin API (screen 17) + ingestion ops: LLM router, budgets, policies, retention and legal hold, users and
roles, taxonomy, extensions. Every change is versioned in ``setting`` and audited; role changes need step-up."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi import Path as PathParam
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l7_governance import audit_service, retention, settings_service
from cortex.l7_governance.policy_engine import GOVERNANCE_PACKAGE, governance_config
from cortex.l8_actuation.api.common import row
from platform_core.auth.deps import OPA_AUTHZ_PACKAGE, authorize
from platform_core.auth.principal import Principal
from platform_core.bus import get_bus
from platform_core.config import get_settings
from platform_core.db import get_session
from platform_core.errors import NotFound
from platform_core.llm.router import get_router
from platform_core.policy.opa import get_opa

router = APIRouter(prefix="/v1", tags=["admin"])

KNOWN_STREAMS = ("system.jobs", "signals.raw", "agents.jobs")


# ----------------------------------------------------------------------------- LLM router + budgets
@router.get("/admin/budgets", summary="Today's LLM spend vs caps (global and per feature)")
async def budgets(
    day: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    _: Principal = Depends(authorize("budget:read", "budget")),
) -> dict[str, Any]:
    out = await get_router().ledger.summary(day)
    out["overrides"] = settings_service.current("budgets")
    return out


class BudgetsIn(BaseModel):
    daily_cap_usd: float | None = Field(None, ge=0, le=100_000)
    feature_caps: dict[str, float] = Field(default_factory=dict)


@router.put("/admin/budgets", summary="Update the daily $ cap and per-feature caps (versioned, audited)")
async def put_budgets(body: BudgetsIn, p: Principal = Depends(authorize("admin:write", "budget")),
                      session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    return await settings_service.put(session, p, "budgets", body.model_dump(exclude_none=True))


@router.get("/admin/llm-router", summary="LLM tier → provider/model/caps (secret refs redacted), with availability")
async def llm_router(_: Principal = Depends(authorize("admin:read", "llm_router"))) -> dict[str, Any]:
    r = get_router()
    return {
        **r.describe(),
        "available": {t: r.available(t) for t in ("small", "mid", "large")},
        "overrides": settings_service.current("llm_router"),
    }


class TierIn(BaseModel):
    model: str | None = Field(None, max_length=120)
    max_tokens: int | None = Field(None, ge=256, le=200_000)
    price_in_per_mtok: float | None = Field(None, ge=0)
    price_out_per_mtok: float | None = Field(None, ge=0)


class RouterIn(BaseModel):
    tiers: dict[Literal["small", "mid", "large"], TierIn]


@router.put("/admin/llm-router", summary="Update tier models / limits / prices (providers and secrets stay in config)")
async def put_llm_router(body: RouterIn, p: Principal = Depends(authorize("admin:write", "llm_router")),
                         session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    value = {"tiers": {k: v.model_dump(exclude_none=True) for k, v in body.tiers.items()}}
    return await settings_service.put(session, p, "llm_router", value)


# ----------------------------------------------------------------------------- policies
@router.get(
    "/admin/policies", summary="OPA policies (Rego source, read-only), roles, and the effective governance settings"
)
def policies(_: Principal = Depends(authorize("admin:read", "policy"))) -> dict[str, Any]:
    d = get_settings().config_dir / "policies"
    files = {f.name: f.read_text(encoding="utf-8") for f in sorted(Path(d).glob("*.rego"))}
    return {"rego": files, "governance": governance_config(), "overrides": settings_service.current("governance"),
            "editable": sorted(settings_service.GOVERNANCE_KEYS), "packages": [OPA_AUTHZ_PACKAGE, GOVERNANCE_PACKAGE]}  # fmt: skip


class PolicyIn(BaseModel):
    governance: dict[str, Any]


@router.put(
    "/admin/policies", summary="Update governance settings used by the Rego (self-approval, hours, allowlist, …)"
)
async def put_policies(body: PolicyIn, p: Principal = Depends(authorize("admin:write", "policy", step_up=True)),
                       session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    return await settings_service.put(session, p, "governance", body.governance)


class PolicyTestIn(BaseModel):
    package: Literal["cortex.authz", "cortex.governance"]
    input: dict[str, Any]


@router.post("/admin/policies/test", summary="Evaluate a policy package against a sample input (no side effects)")
async def test_policy(body: PolicyTestIn, p: Principal = Depends(authorize("admin:read", "policy"))) -> dict[str, Any]:
    d = await get_opa().evaluate(body.package, body.input)
    return {"package": body.package, "allow": d.allow, "deny": d.reasons, "raw": d.raw}


# ----------------------------------------------------------------------------- retention + legal hold
@router.get("/admin/retention", summary="Retention policies (effective), legal holds and recent runs")
async def get_retention(
    _: Principal = Depends(authorize("retention:read", "retention")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    org = get_settings().org_id
    holds = (await session.execute(text("SELECT * FROM legal_hold WHERE org_id = :org ORDER BY released_at NULLS FIRST, created_at DESC LIMIT 200"),
                                   {"org": org})).mappings().all()  # fmt: skip
    runs = (
        (
            await session.execute(
                text("SELECT * FROM retention_run WHERE org_id = :org ORDER BY created_at DESC LIMIT 60"), {"org": org}
            )
        )
        .mappings()
        .all()
    )
    return {"policies": retention.policies(settings_service.current("retention")), "overrides": settings_service.current("retention"),
            "legal_holds": [row(h) for h in holds], "runs": [row(r) for r in runs], "holdable": sorted(retention.HOLDABLE)}  # fmt: skip


class RetentionIn(BaseModel):
    policies: dict[str, dict[str, str]]


@router.put("/admin/retention", summary="Override retention durations (the audit log's 7 years can't be changed)")
async def put_retention(body: RetentionIn, p: Principal = Depends(authorize("admin:write", "retention", step_up=True)),
                        session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    return await settings_service.put(session, p, "retention", body.policies)


class RunIn(BaseModel):
    dry_run: bool = True


@router.post("/admin/retention/run", summary="Run retention now (dry run by default); legal holds always win")
async def run_retention(body: RunIn, p: Principal = Depends(authorize("admin:write", "retention")),
                        session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    return await retention.run(session, p, dry_run=body.dry_run, overrides=settings_service.current("retention"))


class HoldIn(BaseModel):
    target_table: str = Field(max_length=40)
    target_id: str | None = None
    reason: str = Field(min_length=5, max_length=1000)


@router.post(
    "/legal-holds",
    status_code=201,
    tags=["audit"],
    summary="Place a legal hold (row, table, or an opportunity and everything linked)",
)
async def place_hold(body: HoldIn, p: Principal = Depends(authorize("legal_hold:write", "legal_hold")),
                     session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    return await retention.place_hold(session, p, body.target_table, body.target_id, {}, body.reason)


class ReleaseIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


@router.post("/legal-holds/{id}/release", tags=["audit"], summary="Release a legal hold (audited)")
async def release_hold(id: str, body: ReleaseIn, p: Principal = Depends(authorize("legal_hold:write", "legal_hold", step_up=True)),
                       session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    return await retention.release_hold(session, p, id, body.reason)


# ----------------------------------------------------------------------------- users + roles (Keycloak)
@router.get("/admin/users", summary="Users, realm roles and MFA status (Keycloak-synced)")
async def users(
    p: Principal = Depends(authorize("admin:read", "user")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    from cortex.l8_actuation.keycloak_admin import list_users

    out = await list_users()
    await audit_service.record(session, p, "admin.users.read", "user:*", {"count": len(out)})
    from platform_core.auth.rbac import get_rbac

    rbac = get_rbac()
    return {"items": out, "roles": {k: {"mfa": v.get("mfa"), "description": v.get("description")} for k, v in rbac.roles.items() if k != "service"},
            "mfa_enforced": get_settings().oidc_enforce_mfa}  # fmt: skip


class UserRolesIn(BaseModel):
    user_id: str = Field(max_length=64)
    roles: list[str] = Field(max_length=6)


@router.put("/admin/users", summary="Set a user's platform roles (step-up MFA; audited)")
async def put_users(body: UserRolesIn, p: Principal = Depends(authorize("admin:write", "user", step_up=True)),
                    session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    from cortex.l8_actuation.keycloak_admin import set_roles

    out = await set_roles(body.user_id, body.roles)
    await audit_service.record(session, p, "admin.user.roles_set", f"user:{body.user_id}", out)
    return out


# ----------------------------------------------------------------------------- taxonomy + extensions
@router.get("/admin/taxonomy", summary="The 11 capital classes: labels and rule keywords (effective)")
async def taxonomy(_: Principal = Depends(authorize("admin:read", "taxonomy"))) -> dict[str, Any]:
    from cortex.l2_representation.taxonomy import get_taxonomy

    t = get_taxonomy()
    return {"classes": {k: {"label": v.get("label"), "keywords": (v.get("rules") or {}).get("keywords", []), "agent": v.get("agent")}
                        for k, v in t.classes.items()}, "llm_threshold": t.llm_threshold, "overrides": settings_service.current("taxonomy")}  # fmt: skip


class ClassIn(BaseModel):
    label: str | None = Field(None, max_length=80)
    keywords: list[str] | None = Field(None, max_length=80)


class TaxonomyIn(BaseModel):
    classes: dict[str, ClassIn]


@router.put("/admin/taxonomy", summary="Edit class labels / keywords (class keys are fixed); audited")
async def put_taxonomy(body: TaxonomyIn, p: Principal = Depends(authorize("admin:write", "taxonomy")),
                       session: AsyncSession = Depends(get_session, scope="function")) -> dict[str, Any]:  # fmt: skip
    return await settings_service.put(
        session, p, "taxonomy", {"classes": {k: v.model_dump(exclude_none=True) for k, v in body.classes.items()}}
    )


@router.get("/admin/extensions", summary="Extension points (interfaces only; all off)")
async def extensions(_: Principal = Depends(authorize("admin:read", "extension"))) -> dict[str, Any]:
    from cortex import extensions as ext

    return {"extensions": ext.verify(), "note": "Interfaces and flags only (R4); no implementation ships."}


# ----------------------------------------------------------------------------- ingestion ops
@router.get("/ingestion/dlq", tags=["ingestion"], summary="Dead-letter queue contents")
async def dlq(
    stream: str = Query("signals.raw"),
    limit: int = Query(100, ge=1, le=1000),
    _: Principal = Depends(authorize("ingestion:read", "dlq")),
) -> dict[str, Any]:
    if stream not in KNOWN_STREAMS:
        raise NotFound(f"unknown stream {stream}")
    items = await get_bus().dlq_list(stream, limit)
    for i in items:
        i.pop("actor_token", None)  # never echo credentials
    return {"stream": stream, "items": items}


@router.post("/ingestion/dlq/{dlq_id}/replay", tags=["ingestion"], summary="Replay one DLQ message")
async def dlq_replay(
    dlq_id: str = PathParam(pattern=r"^\d{1,20}-\d{1,20}$", description="Redis stream id, e.g. 1727600000000-0"),
    stream: str = Query("signals.raw"),
    p: Principal = Depends(authorize("source:run", "dlq")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    if stream not in KNOWN_STREAMS:
        raise NotFound(f"unknown stream {stream}")
    # the job runs under the replayer's own token: the worker re-checks the job's permission against them, so a
    # replay can't borrow an approver's or admin's identity (e.g. an outbox.release)
    new_id = await get_bus().dlq_replay(stream, dlq_id, actor_token=p.token)
    if new_id is None:
        raise NotFound("DLQ message not found")
    await audit_service.record(
        session, p, "ingestion.dlq_replayed", f"bus:{stream}/{dlq_id}", {"new_stream_id": new_id}
    )
    return {"replayed": dlq_id, "new_stream_id": new_id}
