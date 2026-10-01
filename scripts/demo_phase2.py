"""Phase 2 definition of done, live against the running stack (`make up`, optionally `make seed`):

council on a high-score opportunity → live stream → citation report → approval inbox → approve (fresh login,
the step-up) → outbox released to Mailpit → a second draft edited after approval is invalidated and blocked.

Usage: python scripts/demo_phase2.py [opportunity_id]
Logs in through the real Keycloak browser flow as dev-analyst (requester) and the platform admin from .env
(approver: segregation of duties means the requester can't approve their own request).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "infra" / "keycloak"))
from devtoken import token  # noqa: E402
from generate_realm import DEV_PASSWORD  # noqa: E402

API = os.environ.get("API", "http://localhost:8300")
MAILPIT = os.environ.get("MAILPIT", "http://localhost:8383")


def env_value(key: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{key} is not set in .env")


def step(msg: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {msg}" + (f": {detail}" if detail else ""))
    if not ok:
        raise SystemExit(1)


def main() -> None:
    analyst = token("dev-analyst", DEV_PASSWORD)
    ha = {"Authorization": f"Bearer {analyst}"}
    c = httpx.Client(base_url=API, timeout=60)
    opp = sys.argv[1] if len(sys.argv) > 1 else None
    if not opp:
        # a grant needs one approver; financial terms (e.g. a SAFE) need Admin + Legal, shown in the inbox
        high = c.get("/v1/opportunities?band=high&limit=100&facets=false&sort=score", headers=ha).json()["items"]
        financial = ("convertible",)  # SAFE/note memos carry financial terms: Admin + Legal must both approve
        items = [o for o in high if o["class"] not in financial and "valuation" not in o["title"].lower()] or high
        step("a high-score opportunity exists", bool(items), "run `make seed`, or fill the organisation profile")
        opp = items[0]["id"]
        print(f"      {items[0]['title']} (score {items[0]['score']}, demo={items[0]['is_demo']})")

    r = c.post("/v1/agents/run", headers=ha, json={"opportunity_id": opp})
    step("council queued by the analyst", r.status_code == 202, r.text[:200])
    run_id = r.json()["run_id"]

    seen: list[str] = []
    with c.stream(
        "GET", f"/v1/agents/runs/{run_id}/stream", headers={**ha, "Accept": "text/event-stream"}, timeout=600
    ) as s:
        for line in s.iter_lines():
            if line.startswith("event:"):
                ev = line.split(":", 1)[1].strip()
                seen.append(ev)
                if ev == "run.finished":
                    break
    step("live SSE stream: plan → positions → converge → citation → policy → approval → finished",
         all(e in seen for e in ("plan", "agent.position", "converge", "citation.result", "policy", "run.finished")),
         ", ".join(dict.fromkeys(seen)))  # fmt: skip
    run = c.get(f"/v1/agents/runs/{run_id}", headers=ha).json()
    out = run["output"]
    step("council finished with a cited recommendation", run["status"] in ("succeeded", "partial") and bool(out.get("recommendation_id")),
         f"status {run['status']}, stance {out.get('stance')}, {len(run['agents'])} agents, mode {run.get('mode')}")  # fmt: skip
    cit = out.get("citation") or {}
    step(
        "citation report",
        cit.get("status") in ("pass", "gaps"),
        f"{cit.get('passed')} passed, {cit.get('rejected')} stripped",
    )
    if out.get("stance") != "pursue":
        print(f"      stance is {out.get('stance')}: no outbound action proposed, so there is nothing to approve")
        return
    approval_id, outbox_id = out["approval_id"], out["outbox_id"]

    self_try = c.post(f"/v1/approvals/{approval_id}/decision", headers=ha, json={"decision": "approved"})
    step(
        "the requester can't approve their own request", self_try.status_code == 403, self_try.json().get("detail", "")
    )

    admin = token(env_value("CORTEX_ADMIN_EMAIL"), env_value("CORTEX_ADMIN_PASSWORD"))  # a fresh login = the step-up
    hp = {"Authorization": f"Bearer {admin}"}
    inbox = c.get("/v1/approvals?status=pending", headers=hp).json()
    step(
        "the item is in the approval inbox",
        any(i["id"] == approval_id for i in inbox["items"]),
        f"{inbox['total']} pending",
    )
    d = c.post(
        f"/v1/approvals/{approval_id}/decision", headers=hp, json={"decision": "approved", "comment": "demo"}
    ).json()
    step("approved with a fresh authentication; release queued", d.get("status") == "approved", json.dumps(d)[:200])

    status = None
    for _ in range(30):
        status = c.get(f"/v1/outbox/{outbox_id}", headers=hp).json()
        if status["status"] in ("sent", "blocked"):
            break
        time.sleep(1)
    step(
        "outbox released by the sender (token + hash verified)",
        status["status"] == "sent",
        json.dumps(status.get("delivery"))[:200],
    )
    try:
        mails = httpx.get(f"{MAILPIT}/api/v1/messages", timeout=10).json()
        found = any(outbox_id in (m.get("MessageID") or "") for m in mails.get("messages", []))
        step("delivered to Mailpit (dev SMTP; nothing left the machine)", found or status["channel"] != "email")
    except httpx.HTTPError as e:
        print(f"      Mailpit not reachable ({e}); skipped")

    # editing after approval invalidates it
    draft = c.post("/v1/outbox", headers=ha, json={"channel": "email", "opportunity_id": opp,
                                                    "payload": {"to": "demo@example.org", "subject": "v1", "body": "first"}}).json()  # fmt: skip
    aid = c.post(f"/v1/outbox/{draft['id']}/request-approval", headers=ha).json()["approval_id"]
    d2 = c.post(f"/v1/approvals/{aid}/decision", headers=hp, json={"decision": "approved", "release": "manual"}).json()
    step("second draft approved for later release", d2.get("status") == "approved" and not d2.get("release"))
    e = c.patch(
        f"/v1/outbox/{draft['id']}",
        headers=ha,
        json={"payload": {"to": "demo@example.org", "subject": "v2", "body": "edited"}},
    ).json()
    step("editing the draft invalidates its approval", e.get("status") == "draft", json.dumps(e))
    snd = c.post(f"/v1/outbox/{draft['id']}/send", headers=hp).json()
    step(
        "sending without a valid approval is blocked",
        snd.get("status") == "blocked",
        ", ".join(snd.get("reasons") or []),
    )
    print("PHASE 2 DEMO OK")


if __name__ == "__main__":
    main()
