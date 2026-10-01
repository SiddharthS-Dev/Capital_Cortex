"""citation_checker (I1, I7): the gate every agent / LLM output passes before anyone can see or act on it.

Output schema (agents, convergence, later the Copilot)::

    {"claims": [{"text": str, "kind": "fact" | "inference", "evidence": [ref], "basis": [ref]}]}

A ref is ``<kind>:<id>`` with an optional ``#field``, e.g. ``opportunity:6f1…#deadline`` or
``tool:<agent_run_id>:warm_path``. Each claim passes only when:

1. it cites something: facts need ``evidence``, inferences need ``basis`` (a declared inference over data);
2. every ref resolves to a record and sits inside the caller's authorisation scope (RBAC permission for
   the record kind, classification ≤ clearance);
3. every number in the text matches a number in the cited records within ±0.5 % (I7: models narrate
   computed numbers, they never produce them). A number may also match a token of a cited string (a title
   such as "SBIR Phase II"), and a date must equal a date in the cited records;
4. every organisation-like name ("… Fund", "… Capital", "… Foundation", …) occurs in a cited record, so a
   plausible-sounding investor can't be invented.

On failure the output goes back to its producer (at most 2 revisions). Whatever still fails is stripped and
surfaced as a gap. Every rejection is metered (``cortex_citation_rejections_total``), which feeds the
"spike in unsourced-claim rejections" alert.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

from platform_core.observability.metrics import CITATION_REJECTIONS

TOLERANCE = 0.005  # ±0.5 %
MAX_REVISIONS = 2

REF_RE = re.compile(r"^(?P<kind>[a-z_]+):(?P<id>[A-Za-z0-9_\-:./]+?)(?:#(?P<field>[A-Za-z0-9_.\-/]+))?$")

_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_DATE_PATTERNS = [
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ][0-9:.]+(?:Z|[+-]\d{2}:?\d{2})?)?\b"),
    re.compile(rf"\b(\d{{1,2}})\s+({_MONTHS})[a-z]*\.?,?\s+(\d{{4}})\b", re.I),
    re.compile(rf"\b({_MONTHS})[a-z]*\.?\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.I),
]
_MONTH_NUM = {
    m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])
}
_NUMBER = re.compile(
    r"(?<![\w.])(?P<cur>[$€£])?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s?(?P<suf>%|percent\b|k\b|K\b|m\b|M\b|mn\b|bn\b|B\b|million\b|billion\b|thousand\b)|(?P<per100>/100\b))?"
)
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "b": 1e9, "billion": 1e9}
_ORG_SUFFIX = (
    "Fund|Funds|Capital|Ventures|Venture|Partners|Foundation|Agency|Bank|Institute|University|Programme|Program|"
    "Trust|Holdings|Labs|Inc|LLC|Ltd|GmbH|Corporation|Corp|Authority|Endowment|Investments|Advisors"
)
# Magnitudes spelled out ("five million", "a billion", "twenty percent") can't be checked against a record,
# so a claim must write them as digits.
_WORD_NUMBER = re.compile(
    r"\b(?:a|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty|"
    r"sixty|seventy|eighty|ninety|hundred|several|many)[\s-]+(?:hundred|thousand|million|billion|trillion|percent)\b",
    re.I,
)
_ORG_NAME = re.compile(rf"\b((?:[A-Z][\w&'\-]*\s+){{1,5}}(?:{_ORG_SUFFIX})\b(?:\s+[IVX]{{1,4}}\b)?)")


# ----------------------------------------------------------------------------- data shapes
@dataclass
class Claim:
    text: str
    kind: Literal["fact", "inference"] = "fact"
    evidence: list[str] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, raw: Any) -> Claim | None:
        if not isinstance(raw, dict) or not isinstance(raw.get("text"), str) or not raw["text"].strip():
            return None
        kind: Literal["fact", "inference"] = "inference" if raw.get("kind") == "inference" else "fact"
        return cls(
            text=raw["text"].strip()[:2000],
            kind=kind,
            evidence=[str(r) for r in (raw.get("evidence") or []) if isinstance(r, str | int)][:20],
            basis=[str(r) for r in (raw.get("basis") or []) if isinstance(r, str | int)][:20],
        )

    @property
    def refs(self) -> list[str]:
        return list(dict.fromkeys(self.evidence + self.basis))


@dataclass
class Resolved:
    ref: str
    record: dict[str, Any]  # the cited record (or the cited field's value under "value")
    kind: str


class RefResolver(Protocol):
    async def resolve(self, ref: str) -> Resolved | None:
        """Return the record, or None when it doesn't exist."""

    def in_scope(self, resolved: Resolved) -> bool:
        """True when the caller may read this record (RBAC permission + classification)."""


@dataclass
class ClaimResult:
    claim: Claim
    ok: bool
    problems: list[str] = field(default_factory=list)
    matched_numbers: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"claim": asdict(self.claim), "ok": self.ok, "problems": self.problems, "numbers": self.matched_numbers}


@dataclass
class CitationReport:
    passed: list[ClaimResult] = field(default_factory=list)
    rejected: list[ClaimResult] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    revisions: int = 0
    malformed: int = 0

    @property
    def ok(self) -> bool:
        return not self.rejected and not self.malformed

    @property
    def status(self) -> str:
        if self.ok:
            return "pass"
        return "gaps" if self.passed else "rejected"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checked": len(self.passed) + len(self.rejected),
            "passed": len(self.passed),
            "rejected": len(self.rejected),
            "malformed": self.malformed,
            "revisions": self.revisions,
            "claims": [r.as_dict() for r in self.passed + self.rejected],
            "gaps": self.gaps,
        }


# ----------------------------------------------------------------------------- record flattening
def _walk(value: Any) -> Iterable[Any]:
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _walk(v)
    else:
        yield value


def _numbers_in(record: dict[str, Any]) -> list[float]:
    out: list[float] = []
    for v in _walk(record):
        if isinstance(v, bool):
            continue
        if isinstance(v, int | float | Decimal):
            out.append(float(v))
        elif isinstance(v, str):
            s = v.strip().replace(",", "")
            if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
                out.append(float(s))
    return out


def _strings_in(record: dict[str, Any]) -> list[str]:
    return [v for v in _walk(record) if isinstance(v, str)]


def _dates_in(record: dict[str, Any]) -> set[date]:
    out: set[date] = set()
    for v in _walk(record):
        if isinstance(v, datetime):
            out.add(v.date())
        elif isinstance(v, date):
            out.add(v)
        elif isinstance(v, str):
            m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", v.strip())
            if m:
                try:
                    out.add(date(int(m[1]), int(m[2]), int(m[3])))
                except ValueError:
                    pass
    return out


_ISO_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ][0-9:.]+(?:Z|[+-]\d{2}:?\d{2})?)?")
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _undated(s: str) -> str:
    """Digits inside timestamps and ids aren't quotable numbers ("30" must not match "2026-09-30")."""
    return _UUID_RE.sub(" ", _ISO_DATETIME.sub(" ", s))


def _close(a: float, b: float) -> bool:
    if a == b:
        return True
    return abs(a - b) <= TOLERANCE * max(abs(a), abs(b))


# ----------------------------------------------------------------------------- text extraction
def extract_dates(text: str) -> tuple[list[date], str]:
    """Dates written in the text, and the text with them blanked out (so their digits aren't numbers)."""
    found: list[date] = []

    def _sub(m: re.Match[str], order: str) -> str:
        try:
            if order == "iso":
                d = date(int(m[1]), int(m[2]), int(m[3]))
            elif order == "dmy":
                d = date(int(m[3]), _MONTH_NUM[m[2][:3].lower()], int(m[1]))
            else:
                d = date(int(m[3]), _MONTH_NUM[m[1][:3].lower()], int(m[2]))
            found.append(d)
        except (ValueError, KeyError):
            return m[0]
        return " "

    text = _DATE_PATTERNS[0].sub(lambda m: _sub(m, "iso"), text)
    text = _DATE_PATTERNS[1].sub(lambda m: _sub(m, "dmy"), text)
    text = _DATE_PATTERNS[2].sub(lambda m: _sub(m, "mdy"), text)
    return found, text


def extract_numbers(text: str) -> list[dict[str, Any]]:
    """Numbers in a claim with the candidate values they may stand for (e.g. "74%" → 74 or 0.74)."""
    out = []
    for m in _NUMBER.finditer(text):
        raw = m["num"]
        v = float(raw.replace(",", ""))
        suf = (m["suf"] or "").lower()
        cands = {v}
        if suf in ("%", "percent") or m["per100"]:
            cands.add(v / 100)
        elif suf in _SCALE:
            cands = {v * _SCALE[suf]}
        out.append({"text": m[0].strip(), "raw": raw, "candidates": sorted(cands)})
    return out


def org_names(text: str) -> list[str]:
    return [m.strip() for m in _ORG_NAME.findall(text)]


def _strip_refs(text: str, refs: list[str]) -> str:
    for r in refs:
        text = text.replace(r, " ")
    # bracketed citation markers such as [1] or [ref:…] aren't claims about numbers
    text = re.sub(r"\[(?:\d{1,2}|ref:[^\]]*)\]", " ", text)
    return re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", " ", text)


# ----------------------------------------------------------------------------- checking
async def check_claim(claim: Claim, resolver: RefResolver) -> ClaimResult:
    problems: list[str] = []
    if claim.kind == "fact" and not claim.evidence:
        problems.append("fact cites no evidence")
    if claim.kind == "inference" and not claim.basis:
        problems.append("inference declares no basis")
    records: list[Resolved] = []
    for ref in claim.refs:
        if not REF_RE.match(ref):
            problems.append(f"malformed ref {ref!r}")
            continue
        r = await resolver.resolve(ref)
        if r is None:
            problems.append(f"ref does not resolve: {ref}")
        elif not resolver.in_scope(r):
            problems.append(f"ref outside the caller's authorisation scope: {ref}")
        else:
            records.append(r)
    matched: list[dict[str, Any]] = []
    if records:
        nums = [n for r in records for n in _numbers_in(r.record)]
        strings = [s for r in records for s in _strings_in(r.record)]
        tokens = {t for s in strings for t in re.findall(r"\d+(?:\.\d+)?", _undated(s).replace(",", ""))}
        dates = {d for r in records for d in _dates_in(r.record)}
        years = {d.year for d in dates}
        text_dates, text = extract_dates(_strip_refs(claim.text, claim.refs))
        for d in text_dates:
            if d not in dates:
                problems.append(f"date {d.isoformat()} is not in the cited records")
        for n in extract_numbers(text):
            hit = next(((c, x) for c in n["candidates"] for x in nums if _close(c, x)), None)
            if hit:
                matched.append({"text": n["text"], "value": hit[1]})
            elif n["raw"].replace(",", "") in tokens:
                matched.append({"text": n["text"], "value": n["raw"], "match": "quoted"})
            elif float(n["raw"].replace(",", "")).is_integer() and int(float(n["raw"].replace(",", ""))) in years:
                matched.append({"text": n["text"], "value": n["raw"], "match": "year"})
            else:
                problems.append(f"number {n['text']!r} does not match the cited records (±0.5%)")
        for m in _WORD_NUMBER.finditer(text):
            if m[0].lower() not in " ".join(strings).lower():
                problems.append(f"spelled-out number {m[0]!r} can't be checked; write it in digits from the record")
        haystack = " ".join(strings).lower()
        for name in org_names(claim.text):
            if name.lower() not in haystack:
                problems.append(f"entity {name!r} does not appear in the cited records")
    return ClaimResult(claim, not problems, problems, matched)


async def check(raw_claims: list[Any], resolver: RefResolver, agent: str = "unknown") -> CitationReport:
    report = CitationReport()
    for raw in raw_claims or []:
        c = Claim.parse(raw)
        if c is None:
            report.malformed += 1
            continue
        res = await check_claim(c, resolver)
        (report.passed if res.ok else report.rejected).append(res)
    if report.rejected or report.malformed:
        CITATION_REJECTIONS.labels(agent=agent).inc(len(report.rejected) + report.malformed)
    return report


Reviser = Callable[[CitationReport, int], Awaitable[list[Any] | None]]


async def check_with_revisions(
    raw_claims: list[Any], resolver: RefResolver, agent: str, revise: Reviser | None = None
) -> CitationReport:
    """Check; send failures back to the producer up to ``MAX_REVISIONS`` times; strip what still fails."""
    report = await check(raw_claims, resolver, agent)
    attempt = 0
    while not report.ok and revise is not None and attempt < MAX_REVISIONS:
        attempt += 1
        revised = await revise(report, attempt)
        if revised is None:
            break
        report = await check(revised, resolver, agent)
    report.revisions = attempt
    for r in report.rejected:
        report.gaps.append(f"Unsupported claim removed: “{r.claim.text[:240]}” ({'; '.join(r.problems[:3])})")
    if report.malformed:
        report.gaps.append(f"{report.malformed} malformed claim(s) removed")
    return report


def collateral_gaps(report: CitationReport) -> tuple[list[str], list[dict[str, Any]]]:
    """For documents that leave the platform: a stripped claim becomes a neutral gap that never repeats its text
    (a fabrication must not reach the reader, even quoted); the details stay internal for reviewers."""
    gaps = []
    if report.rejected:
        gaps.append(
            f"{len(report.rejected)} statement(s) in this section could not be matched to a source record and were removed"
        )
    if report.malformed:
        gaps.append(f"{report.malformed} malformed statement(s) removed")
    stripped = [{"text": r.claim.text, "problems": r.problems} for r in report.rejected]
    return gaps, stripped


def revision_feedback(report: CitationReport) -> str:
    """What the producer is told when its claims fail: which claim, and why. No new facts are supplied."""
    lines = [
        "These claims failed the citation check. Fix or drop each one. Cite only refs you were given; "
        "copy numbers exactly from the cited record; never add facts:"
    ]
    for r in report.rejected:
        lines.append(f"- “{r.claim.text[:300]}”: {'; '.join(r.problems)}")
    return "\n".join(lines)
