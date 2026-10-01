"""Eval gates (§14, `make eval`). Fails CI when a gate that applies to the current phase fails.

Each gate declares the phase in which it becomes enforceable. Gates for later phases are reported as
PENDING with their phase. They are never reported as passed (working rule 2: no silent stubs).

  (a) no_fabrication        — ungrounded golden prompts must yield gaps, never invented entities or numbers
  (b) grounding             — every claim in generated collateral resolves to a source
  (c) classification_acc    — ≥ 0.85 on the labelled set
  (d) scoring_sanity        — monotonicity and weight sensitivity
  (t) traceability          — every SyRS item has a linked, existing test
  (s) invariant_schema      — I1/I2/I6 constraints are present in the migration
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cortex.phases import CURRENT_PHASE  # noqa: E402


@dataclass
class Gate:
    key: str
    title: str
    phase: int
    run: Callable[[], tuple[bool, str]] | None


def traceability() -> tuple[bool, str]:
    p = subprocess.run(  # noqa: S603 - fixed argv, no user input
        [sys.executable, str(ROOT / "scripts" / "check_traceability.py")], capture_output=True, text=True, check=False
    )
    return p.returncode == 0, (p.stdout + p.stderr).strip().splitlines()[-1]


def invariant_schema() -> tuple[bool, str]:
    """Static check that the invariant constraints are in the schema (the integration tests exercise them)."""
    mig = (ROOT / "migrations" / "versions" / "0001_initial.py").read_text(encoding="utf-8")
    required = {
        "I1 provenance CHECK": r"source_ref IS NOT NULL.*?OR inference_id IS NOT NULL",
        "I1 inference basis": r"basis_refs jsonb NOT NULL",
        "I2 evidence NOT NULL": r"evidence jsonb NOT NULL",
        "I2 reasoning NOT NULL": r"reasoning jsonb NOT NULL",
        "I3 outbox approval CHECK": r"status NOT IN \('approved','sent'\) OR approval_id IS NOT NULL",
        "I3 edit invalidates approval": r"outbox_invalidate_on_edit",
        "I6 realised labels only": r"CHECK \(label_source = 'realised'\)",
        "audit append-only trigger": r"audit_log_immutable",
    }
    missing = [k for k, rx in required.items() if not re.search(rx, mig, re.S)]
    return not missing, "all present" if not missing else f"missing: {', '.join(missing)}"


def classification_accuracy() -> tuple[bool, str]:
    import yaml

    from cortex.l1_perception.models import Signal
    from cortex.l2_representation.classifier import classify_rules

    items = yaml.safe_load((ROOT / "evals" / "golden_sets" / "classification.yaml").read_text(encoding="utf-8"))[
        "items"
    ]
    misses = []
    for it in items:
        sig = Signal(
            source_key="eval",
            title=it["title"],
            description=it.get("description"),
            investor_type=it.get("investor_type"),
            counterparty_kind=it.get("counterparty_kind"),
            class_hint=it.get("class_hint"),
        )
        got = classify_rules(sig).capital_class
        if got != it["expect"]:
            misses.append(f"{it['title'][:40]}: {got} != {it['expect']}")
    acc = 1 - len(misses) / len(items)
    detail = f"accuracy {acc:.3f} on {len(items)} labelled items"
    if misses:
        detail += " · misses: " + "; ".join(misses[:5])
    return acc >= 0.85, detail


def scoring_sanity() -> tuple[bool, str]:
    """Monotonicity and weight sensitivity of the score formula over 2,000 random cases (seeded)."""
    import random

    from cortex.l4_reasoning.factors import FactorResult
    from cortex.l4_reasoning.score_service import combine, default_profile

    rnd = random.Random(42)  # noqa: S311
    prof = default_profile()
    names = [k for k, f in prof["factors"].items() if f["weight"] > 0]
    failures: list[str] = []
    for case in range(2000):
        vals = {n: (None if rnd.random() < 0.2 else rnd.random()) for n in names}
        res = {n: FactorResult(v, "eval") for n, v in vals.items()}
        base = combine(res, prof)
        if base.score is None:
            continue
        n = rnd.choice([k for k, v in vals.items() if v is not None])
        # monotonicity: raising one available factor never lowers the score
        up = dict(res)
        up[n] = FactorResult(min(1.0, vals[n] + 0.1), "eval")
        if combine(up, prof).score < base.score - 1e-9:
            failures.append(f"monotonicity case {case}")
        # weight sensitivity: more weight on a factor above the score raises it; below the score lowers it
        heavier = {
            "factors": {**prof["factors"], n: {**prof["factors"][n], "weight": prof["factors"][n]["weight"] + 0.2}},
            "thresholds": prof["thresholds"],
        }
        s2 = combine(res, heavier).score
        if (vals[n] > base.score and s2 < base.score - 1e-9) or (vals[n] < base.score and s2 > base.score + 1e-9):
            failures.append(f"sensitivity case {case}")
        # completeness never exceeds 1, and a gap never counts as zero
        if not 0 <= base.completeness <= 1:
            failures.append(f"completeness case {case}")
    return not failures, "2,000 randomised cases" + (
        f" · {len(failures)} failures, e.g. {failures[:3]}" if failures else " · all properties hold"
    )


def no_fabrication() -> tuple[bool, str]:
    """Ungrounded golden questions: every fabricated claim becomes a gap; grounded controls still pass."""
    import asyncio

    import yaml

    from cortex.l7_governance.citation_checker import Resolved, check_with_revisions

    g = yaml.safe_load((ROOT / "evals" / "golden_sets" / "no_fabrication.yaml").read_text(encoding="utf-8"))
    records, hidden = g["records"], set(g.get("out_of_scope") or [])

    class Resolver:
        async def resolve(self, ref: str) -> Resolved | None:
            rec = records.get(ref)
            return Resolved(ref, rec, ref.split(":")[0]) if rec is not None else None

        def in_scope(self, r: Resolved) -> bool:
            return r.ref not in hidden

    failures: list[str] = []
    fabricated = 0

    async def run() -> None:
        nonlocal fabricated
        for case in g["cases"]:
            rep = await check_with_revisions(case["output"], Resolver(), "eval")
            want = int(case.get("expect_pass", 0))
            if want:
                if len(rep.passed) != want:
                    failures.append(f"control over-rejected: {case['question'][:40]} ({len(rep.passed)}/{want})")
                continue
            fabricated += len(case["output"])
            if rep.passed:
                failures.append(f"fabrication passed: {rep.passed[0].claim.text[:60]}")
            if len(rep.gaps) < len(case["output"]):
                failures.append(f"missing gaps for: {case['question'][:40]}")

    asyncio.run(run())
    detail = f"{len(g['cases'])} golden cases, {fabricated} fabricated claims"
    return not failures, detail + (" · " + "; ".join(failures[:4]) if failures else " · all became gaps, controls pass")


def grounding() -> tuple[bool, str]:
    """Generated collateral: every rendered claim resolves and passes the checker; fabrications never render;
    every gap is rendered as [EVIDENCE REQUIRED]; every marker has an appendix row (docx + pptx)."""
    import asyncio
    import io

    import yaml

    from cortex.l6_agency.tool_registry import ToolResult
    from cortex.l7_governance.citation_checker import Resolved, check_with_revisions, collateral_gaps
    from cortex.l8_actuation import asset_generator as ag
    from cortex.l8_actuation.proposal_builder import compose, gap, packages

    g = yaml.safe_load((ROOT / "evals" / "golden_sets" / "grounding.yaml").read_text(encoding="utf-8"))
    records = g["records"]

    def resolve_field(ref: str) -> Resolved | None:
        base, _, fld = ref.partition("#")
        rec = records.get(base)
        if rec is None:
            return None
        if fld:
            cur = rec
            for part in fld.split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            return (
                Resolved(ref, {"field": fld, "value": cur, "name": rec.get("name")}, base.split(":")[0])
                if cur is not None
                else None
            )
        return Resolved(ref, rec, base.split(":")[0])

    class Resolver:
        async def resolve(self, ref: str) -> Resolved | None:
            return resolve_field(ref)

        def in_scope(self, r: Resolved) -> bool:
            return True

    results = {
        k: ToolResult(k, {}, facts=v, gaps=list(g.get("tool_gaps", {}).get(k, []))) for k, v in g["tool_facts"].items()
    }
    for k, v in g.get("tool_gaps", {}).items():
        results.setdefault(k, ToolResult(k, {}, gaps=list(v)))
    order = packages()["packages"][g["package"]]["sections"]
    draft = compose(
        order,
        g["self"],
        g["opportunity"],
        results,
        lambda k: f"tool:run:{k}",
        {"budget": None, "esg": None, "recommendation": None},
    )
    failures: list[str] = []

    async def run() -> list[dict]:
        out = []
        for key in order:
            rep = await check_with_revisions(draft.claims.get(key, []), Resolver(), "eval")
            safe, _stripped = collateral_gaps(rep)
            gaps = list(draft.gaps.get(key, [])) + safe
            out.append(
                {
                    "key": key,
                    "title": key,
                    "claims": [r.claim.__dict__ for r in rep.passed],
                    "gaps": [gap(key, x) for x in gaps],
                }
            )
        return out

    sections = asyncio.run(run())
    m = ag.build_model(title="Grounding eval", subtitle="", artefact="investment_memo", sections=sections,
                       ref_labels={r: ("record", "") for r in records})  # fmt: skip
    from docx import Document
    from pptx import Presentation

    docx_text = chr(10).join(x.text for x in Document(io.BytesIO(ag.render_docx(m))).paragraphs)
    pptx_text = chr(10).join(
        sh.text_frame.text
        for sl in Presentation(io.BytesIO(ag.render_pptx(m))).slides
        for sh in sl.shapes
        if sh.has_text_frame
    )
    rendered = [c for s_ in sections for c in s_["claims"]]
    if "Aurora" in docx_text or "Aurora" in pptx_text:
        failures.append("a fabricated claim was rendered")
    for c in rendered:
        for r in c["evidence"] + c["basis"]:
            if resolve_field(r) is None:
                failures.append(f"unresolvable ref {r}")
    n_gaps = sum(len(s_["gaps"]) for s_ in sections)
    if docx_text.count("[EVIDENCE REQUIRED:") != n_gaps:
        failures.append(f"docx shows {docx_text.count('[EVIDENCE REQUIRED:')} gap blocks, expected {n_gaps}")
    used = {n for it in (i for s_ in m.sections for i in s_.items) for n in it.marks}
    if used != {a.n for a in m.appendix}:
        failures.append("citation markers and appendix rows differ")
    detail = f"{len(rendered)} rendered claims, {len(m.appendix)} appendix refs, {n_gaps} gaps"
    return not failures, detail + (
        " · " + "; ".join(failures[:4]) if failures else " · all grounded, fabrication stripped"
    )


GATES = [
    Gate("t", "traceability", 0, traceability),
    Gate("s", "invariant_schema", 0, invariant_schema),
    Gate("d", "scoring_sanity (monotonicity, weight sensitivity)", 1, scoring_sanity),
    Gate("c", "classification_acc >= 0.85", 1, classification_accuracy),
    Gate("a", "no_fabrication (golden ungrounded prompts)", 2, no_fabrication),
    Gate("b", "grounding (collateral claims resolve)", 3, grounding),
]


def main() -> int:
    print(f"Capital Cortex eval gates, current phase {CURRENT_PHASE}")
    failed = 0
    for g in GATES:
        if g.phase > CURRENT_PHASE:
            print(f"  [PENDING  ] ({g.key}) {g.title}: enforced from Phase {g.phase}")
            continue
        if g.run is None:
            print(f"  [FAIL     ] ({g.key}) {g.title}: due in Phase {g.phase} but not implemented")
            failed += 1
            continue
        ok, detail = g.run()
        print(f"  [{'PASS' if ok else 'FAIL':9}] ({g.key}) {g.title}: {detail}")
        failed += 0 if ok else 1
    print("EVAL OK" if not failed else f"EVAL FAILED ({failed} gate(s))")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
