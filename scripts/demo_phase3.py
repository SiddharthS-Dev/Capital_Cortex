"""Phase 3 definition of done, live against the running stack (after `make seed` for demo data):

VC package (live-formula financial model, evidence appendix, gaps → Admin waivers → approval), all artefacts
exported (docx/pptx/xlsx/pdf), a DD package from approved documents with an approval-gated share link (e-mailed
through Mailpit, downloaded by the recipient), a board pack approved and distributed, the Copilot (grounded and
refused), and the compliance report. Saves the generated files to docs/samples/ (DEMO data, fictional).

Usage: python scripts/demo_phase3.py
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "infra" / "keycloak"))
from demo_phase2 import env_value, step  # noqa: E402
from devtoken import token  # noqa: E402
from generate_realm import DEV_PASSWORD  # noqa: E402

API = os.environ.get("API", "http://localhost:8300")
MAILPIT = os.environ.get("MAILPIT", "http://localhost:8383")
OUT = ROOT / "docs" / "samples"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ha = {"Authorization": f"Bearer {token('dev-analyst', DEV_PASSWORD)}"}
    c = httpx.Client(base_url=API, timeout=180)
    high = c.get("/v1/opportunities?band=high&limit=50&facets=false&sort=score", headers=ha).json()["items"]
    opp = next((o for o in high if o["class"] not in ("convertible",)), high[0] if high else None)
    step("a high-score opportunity exists", opp is not None, "run `make seed` first")
    print(f"      {opp['title']} (demo={opp['is_demo']})")

    # ---- VC package
    r = c.post("/v1/proposals", headers=ha, json={"opportunity_id": opp["id"], "package_type": "vc_pitch"})
    step("VC package generated from sourced evidence", r.status_code == 201, r.text[:200])
    pid = r.json()["id"]
    p = c.get(f"/v1/proposals/{pid}", headers=ha).json()
    claims = [x for s in p["sections"] for x in s["claims"]]
    step(
        "every claim is cited",
        all(x["evidence"] or x["basis"] for x in claims),
        f"{len(claims)} claims, {p['open_gaps']} gaps, mode {p['mode']}",
    )
    for art, fmt in (("pitch_deck", "pptx"), ("pitch_deck", "pdf"), ("executive_summary", "docx"), ("executive_summary", "pdf"),
                     ("investment_memo", "docx"), ("financial_model", "xlsx"), ("dd_checklist", "xlsx")):  # fmt: skip
        e = c.get(f"/v1/proposals/{pid}/export", headers=ha, params={"artefact": art, "fmt": fmt})
        step(
            f"export {art}.{fmt}",
            e.status_code == 200 and hashlib.sha256(e.content).hexdigest() == e.headers["X-Content-SHA256"],
            e.text[:120] if e.status_code != 200 else f"{len(e.content):,} bytes",
        )
        (OUT / f"DEMO-{art}.{fmt}").write_bytes(e.content)
    from openpyxl import load_workbook

    fm = load_workbook(io.BytesIO((OUT / "DEMO-financial_model.xlsx").read_bytes()))
    step(
        "financial model uses live formulas",
        str(fm["Projection"]["G2"].value).startswith("=") and str(fm["Runway"]["B1"].value).startswith("="),
    )
    step("PDF rendered in the API image", (OUT / "DEMO-executive_summary.pdf").read_bytes()[:4] == b"%PDF")

    sub = c.post(f"/v1/proposals/{pid}/submit", headers=ha)
    step("open gaps block approval", sub.status_code == 409, sub.json().get("title", ""))
    admin = {"Authorization": f"Bearer {token(env_value('CORTEX_ADMIN_EMAIL'), env_value('CORTEX_ADMIN_PASSWORD'))}"}
    p = c.get(f"/v1/proposals/{pid}", headers=ha).json()
    for g in [g for g in p["gaps"] if not g["waived"]]:
        c.post(
            f"/v1/proposals/{pid}/sections/{g['section']}/gaps/{g['id']}/waive",
            headers=admin,
            json={"reason": "demo walkthrough waiver"},
        ).raise_for_status()
    sub = c.post(f"/v1/proposals/{pid}/submit", headers=ha)
    step("waived by an Admin (audited), then submitted", sub.status_code == 200, sub.text[:160])
    d = c.post(
        f"/v1/approvals/{sub.json()['approval_id']}/decision", headers=admin, json={"decision": "approved"}
    ).json()
    step("proposal approved", d.get("status") == "approved", json.dumps(d)[:160])

    # ---- DD package + share link
    ids = []
    for title, tag in (
        ("Capitalisation table (DEMO)", "cap_table"),
        ("Financial statements FY2025 (DEMO)", "financials"),
    ):
        u = c.post("/v1/dataroom/documents", headers=ha, files={"file": (f"{title}.pdf", (OUT / "DEMO-executive_summary.pdf").read_bytes())},
                   data={"title": title, "folder": "/demo", "dd_tags": tag, "classification": "confidential"})  # fmt: skip
        step(f"upload {title}", u.status_code == 201, u.text[:120])
        ids.append(u.json()["id"])
        c.patch(
            f"/v1/dataroom/documents/{u.json()['id']}", headers=admin, json={"approved_repo": True}
        ).raise_for_status()
    pk = c.post("/v1/dataroom/packages", headers=ha, json={"name": "DEMO seed DD package", "document_ids": ids})
    step("DD package assembled from approved documents", pk.status_code == 201, pk.text[:120])
    sh = c.post(
        f"/v1/dataroom/packages/{pk.json()['id']}/share",
        headers=ha,
        json={"recipient": "partner@fund.example", "expires_in_days": 7},
    ).json()
    c.post(
        f"/v1/approvals/{sh['approval_id']}/decision", headers=admin, json={"decision": "approved"}
    ).raise_for_status()
    link = None
    for _ in range(30):
        msgs = httpx.get(
            f"{MAILPIT}/api/v1/search", params={"query": 'subject:"Data room: DEMO seed DD package"'}, timeout=10
        ).json()
        if msgs.get("messages"):
            body = httpx.get(f"{MAILPIT}/api/v1/message/{msgs['messages'][0]['ID']}", timeout=10).json()["Text"]
            link = re.search(r"(http\S+/v1/share/\S+)", body)
            break
        time.sleep(1)
    step("share link e-mailed after approval (Mailpit)", link is not None)
    z = httpx.get(link.group(1), timeout=30)
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    man = json.loads(zf.read("MANIFEST.json"))
    step(
        "recipient download verifies against the manifest",
        all(hashlib.sha256(zf.read(f["path"])).hexdigest() == f["sha256"] for f in man["files"]),
    )

    # ---- board pack
    today = date.today()
    b = c.post("/v1/board-reports", headers=ha, json={"period_start": str(today - timedelta(days=90)), "period_end": str(today),
                                                      "recipients": ["board@inspironics.net"], "include_demo": False}).json()  # fmt: skip
    for fmt in ("pdf", "pptx"):
        e = c.get(f"/v1/board-reports/{b['id']}/export", headers=ha, params={"fmt": fmt})
        (OUT / f"DEMO-board-pack.{fmt}").write_bytes(e.content)
    s = c.post(f"/v1/board-reports/{b['id']}/submit", headers=ha).json()
    d = c.post(f"/v1/approvals/{s['approval_id']}/decision", headers=admin, json={"decision": "approved"}).json()
    if d.get("status") == "pending":
        print(
            f"      board pack needs more approvals by policy: {d.get('remaining')} (a Legal approver must also approve)"
        )
        print(f"PHASE 3 DEMO OK (board distribution awaits Legal) · samples in {OUT}")
        return
    step(
        "board pack approved; distribution queued",
        d.get("status") == "approved" and d["follow_up"]["distribution"],
        json.dumps(d)[:160],
    )
    for _ in range(30):
        rep = c.get(f"/v1/board-reports/{b['id']}", headers=ha).json()
        if rep["distribution"] and rep["distribution"][0].get("outbox_status") == "sent":
            break
        time.sleep(1)
    step("board pack distributed through the outbox", rep["distribution"][0].get("outbox_status") == "sent")

    # ---- Copilot
    def ask(q: str, opp_id: str | None = None) -> dict:
        last = {}
        with c.stream("POST", "/v1/copilot/ask", headers=ha, json={"question": q, "opportunity_id": opp_id}) as st:
            for line in st.iter_lines():
                if line.startswith("data:"):
                    last = json.loads(line[5:])
        return last

    a = ask("Why is this ranked where it is?", opp["id"])
    step("Copilot answers with citations", a["grounded"], a["answer"][:140])
    a = ask("What is the airspeed velocity of an unladen swallow?")
    step("Copilot refuses without sourced evidence", not a["grounded"], a["answer"])
    rep = c.get(
        "/v1/audit/compliance-report", headers=admin, params={"from": str(today - timedelta(days=30)), "to": str(today)}
    )
    (OUT / "DEMO-compliance-report.xlsx").write_bytes(rep.content)
    step("compliance report exported", rep.status_code == 200)
    print(f"PHASE 3 DEMO OK · samples in {OUT}")


if __name__ == "__main__":
    main()
