"""Security scans (§14; `make scan`): Trivy (images + dependencies) and OWASP ZAP (UI baseline + API).

    trivy image  capital-cortex/api:dev, capital-cortex/web:dev   (HIGH,CRITICAL, --ignore-unfixed)
    trivy fs     apps/web/package-lock.json and constraints.txt (scanned as requirements.txt)
    zap-baseline.py   the UI            (default http://host.docker.internal:$WEB_PORT)
    zap-api-scan.py   the API OpenAPI   (default http://host.docker.internal:$API_PORT/v1/openapi.json), safe
                      mode (passive only) unless --active; --active-token-user adds a real bearer token

Active API scans send attack payloads: point --api at the load-profile API (`api-load`, synthetic data), never
at an environment with real data. Exit 1 when Trivy finds a fixable HIGH/CRITICAL or ZAP reports a FAIL / High
alert. Reports: --out DIR (default: a temp dir, printed at the end).

Usage: python scripts/scan.py [--skip-trivy] [--skip-zap] [--ui URL] [--api URL] [--active]
       [--active-token-user dev-analyst] [--network NET] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from ops_common import ROOT, dump_json, log, out, run, setting

TRIVY = "aquasec/trivy:0.74.0"
ZAP = "ghcr.io/zaproxy/zaproxy:stable"
IMAGES = ["capital-cortex/api:dev", "capital-cortex/web:dev"]
TRIVY_CACHE = "capital-cortex-trivy-cache"


def trivy(args: list[str], mounts: list[str], dest: Path) -> dict[str, Any]:
    argv = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{TRIVY_CACHE}:/root/.cache",
        *[x for m in mounts for x in ("-v", m)],
        TRIVY,
        *args,
        "--scanners",
        "vuln",
        "--severity",
        "HIGH,CRITICAL",
        "--ignore-unfixed",
        "--format",
        "json",
    ]
    p = run(argv, check=False, timeout=1800)
    if p.returncode != 0:
        raise RuntimeError(f"trivy failed: {p.stderr.decode('utf-8', 'replace')[-800:]}")
    dest.write_bytes(p.stdout)
    d = json.loads(p.stdout)
    findings = []
    for r in d.get("Results") or []:
        for v in r.get("Vulnerabilities") or []:
            findings.append(
                {
                    "target": r["Target"],
                    "id": v["VulnerabilityID"],
                    "severity": v["Severity"],
                    "pkg": v["PkgName"],
                    "installed": v.get("InstalledVersion"),
                    "fixed": v.get("FixedVersion"),
                }
            )
    os_ = (d.get("Metadata") or {}).get("OS") or {}
    return {
        "os": f"{os_.get('Family', '')} {os_.get('Name', '')}".strip() or None,
        "targets": [r["Target"] for r in d.get("Results") or []],
        "findings": findings,
    }


def zap(script: str, target: str, name: str, outdir: Path, extra: list[str], network: str | None) -> dict[str, Any]:
    net = ["--network", network] if network else ["--add-host", "host.docker.internal:host-gateway"]
    argv = [
        "docker",
        "run",
        "--rm",
        "--memory",
        "1536m",
        "--memory-swap",
        "1536m",
        *net,
        "-v",
        f"{outdir}:/zap/wrk:rw",
        ZAP,
        script,
        "-t",
        target,
        "-J",
        f"{name}.json",
        "-r",
        f"{name}.html",
        "-I",
        *extra,
    ]
    p = run(argv, check=False, timeout=3600)
    report = outdir / f"{name}.json"
    if not report.exists():
        raise RuntimeError(
            f"ZAP {script} produced no report (exit {p.returncode}): {p.stdout.decode('utf-8', 'replace')[-800:]}"
        )
    d = json.loads(report.read_text(encoding="utf-8"))
    alerts = []
    for site in d.get("site", []):
        for a in site.get("alerts", []):
            alerts.append(
                {
                    "id": a["pluginid"],
                    "alert": a["alert"],
                    "risk": a["riskdesc"].split(" ")[0],
                    "count": len(a.get("instances", [])),
                }
            )
    fails = sum(
        1
        for line in p.stdout.decode("utf-8", "replace").splitlines()
        if line.startswith("FAIL-NEW:") and not line.startswith("FAIL-NEW: 0")
    )
    return {"target": target, "exit": p.returncode, "fail_lines": fails, "alerts": alerts}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-trivy", action="store_true")
    ap.add_argument("--skip-zap", action="store_true")
    ap.add_argument("--ui", default=f"http://host.docker.internal:{setting('WEB_PORT', '3300')}")
    ap.add_argument("--api", default=f"http://host.docker.internal:{setting('API_PORT', '8300')}/v1/openapi.json")
    ap.add_argument("--active", action="store_true", help="active API scan (attacks!) instead of safe mode")
    ap.add_argument("--active-token-user", help="send a real access token for this dev user (e.g. dev-analyst)")
    ap.add_argument("--network", help="docker network for ZAP (e.g. capital-cortex_default to reach api-load:8000)")
    ap.add_argument("--out", help="report directory (default: a new temp dir)")
    args = ap.parse_args()

    outdir = Path(args.out).resolve() if args.out else Path(tempfile.mkdtemp(prefix="cortex-scan-"))
    outdir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {"tools": {}, "trivy": {}, "zap": {}}
    bad = 0
    if not args.skip_trivy:
        summary["tools"]["trivy"] = out(["docker", "run", "--rm", TRIVY, "--version"]).splitlines()[0]
        for img in IMAGES:
            log(f"trivy image {img}")
            r = trivy(
                ["image", img],
                ["/var/run/docker.sock:/var/run/docker.sock"],
                outdir / f"trivy-{img.split('/')[-1].replace(':', '-')}.json",
            )
            summary["trivy"][img] = r
            bad += len(r["findings"])
        log("trivy fs: apps/web/package-lock.json, constraints.txt")
        with tempfile.TemporaryDirectory(prefix="cortex-deps-") as d:
            shutil.copy(ROOT / "constraints.txt", Path(d) / "requirements.txt")
            shutil.copy(ROOT / "apps" / "web" / "package-lock.json", Path(d) / "package-lock.json")
            r = trivy(["fs", "/src"], [f"{d}:/src:ro"], outdir / "trivy-deps.json")
        summary["trivy"]["dependencies"] = r
        bad += len(r["findings"])
    if not args.skip_zap:
        summary["tools"]["zap"] = out(["docker", "run", "--rm", ZAP, "zap.sh", "-version"], check=False).splitlines()[
            -1
        ]
        log(f"zap-baseline {args.ui}")
        summary["zap"]["ui"] = zap("zap-baseline.py", args.ui, "zap-ui", outdir, [], args.network)
        extra = ["-f", "openapi"] + ([] if args.active else ["-S"])
        if args.active_token_user:
            sys.path.insert(0, str(ROOT / "scripts"))
            from load_test import get_token

            os.environ["LOAD_TEST_USER"] = args.active_token_user
            tok = get_token()
            extra += [
                "-z",
                "-config scanner.maxScanDurationInMins=12 -config scanner.threadPerHost=2 "
                "-config replacer.full_list(0).description=auth -config replacer.full_list(0).enabled=true "
                "-config replacer.full_list(0).matchtype=REQ_HEADER "
                "-config replacer.full_list(0).matchstr=Authorization -config replacer.full_list(0).regex=false "
                f"-config replacer.full_list(0).replacement=Bearer\\ {tok}",
            ]
        log(f"zap-api-scan ({'ACTIVE' if args.active else 'safe'}) {args.api}")
        summary["zap"]["api"] = zap("zap-api-scan.py", args.api, "zap-api", outdir, extra, args.network)
        for z in summary["zap"].values():
            bad += z["fail_lines"] + sum(1 for a in z["alerts"] if a["risk"] == "High")
    (outdir / "summary.json").write_text(dump_json(summary), encoding="utf-8")

    print("\n=== Security scan summary ===")
    for k, r in summary["trivy"].items():
        print(f"trivy {k:28} {r['os'] or '':18} HIGH/CRITICAL fixable: {len(r['findings'])}")
        for f in r["findings"][:15]:
            print(f"    {f['severity']:8} {f['id']:20} {f['pkg']} {f['installed']} -> {f['fixed']}")
    for k, z in summary["zap"].items():
        by: dict[str, int] = {}
        for a in z["alerts"]:
            by[a["risk"]] = by.get(a["risk"], 0) + 1
        print(f"zap   {k:4} {z['target']}: {by or 'no alerts'}")
        for a in z["alerts"]:
            if a["risk"] != "Informational":
                print(f"    {a['risk']:8} [{a['id']}] {a['alert']} x{a['count']}")
    print(f"reports: {outdir}")
    print("RESULT: " + ("FAIL" if bad else "PASS (no fixable HIGH/CRITICAL, no ZAP FAIL/High)"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
