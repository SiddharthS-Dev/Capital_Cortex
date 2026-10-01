"""Phase 2 L7: citation_checker (I1/I7), approval tokens (I3), content flags."""

import time

import jwt
import pytest

from cortex.l7_governance.citation_checker import (
    Resolved,
    check,
    check_with_revisions,
    extract_numbers,
    org_names,
    revision_feedback,
)
from cortex.l7_governance.policy_engine import content_flags, required_approvals
from platform_core.signing import ApprovalTokenSigner, InvalidApprovalToken, SigningKeyMissing, content_hash

OPP = "opportunity:11111111-1111-1111-1111-111111111111"
TOOL = "tool:22222222-2222-2222-2222-222222222222:runway"
SECRET = "opportunity:33333333-3333-3333-3333-333333333333"


class FakeResolver:
    def __init__(self, records, out_of_scope=()):
        self.records = records
        self.out = set(out_of_scope)

    async def resolve(self, ref):
        rec = self.records.get(ref)
        return Resolved(ref, rec, ref.split(":")[0]) if rec is not None else None

    def in_scope(self, r):
        return r.ref not in self.out


RECORDS = {
    OPP: {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "SBIR Phase II Clean Energy 2027",
        "score": 0.7412,
        "completeness": 0.8,
        "amount_max": 1250000,
        "deadline": "2026-11-15T17:00:00+00:00",
        "counterparty": "Northwind Climate Fund I",
    },
    TOOL: {"runway_months": 14.3333, "zero_cash_date": "2027-12-01", "as_of": "2026-09-30T10:00:00+00:00"},
    SECRET: {"title": "Restricted", "score": 0.5},
}


def fact(text, *refs):
    return {"text": text, "kind": "fact", "evidence": list(refs)}


async def test_supported_claims_pass():
    rep = await check(
        [
            fact("“SBIR Phase II Clean Energy 2027” scores 74.1% with 80.0% evidence completeness.", OPP),
            fact("The stated amount is USD 1,250,000 and the deadline is 2026-11-15.", OPP),
            fact("Base-case runway is 14.33 months (zero cash 2027-12-01).", TOOL),
            fact("Northwind Climate Fund I is the counterparty.", OPP),
        ],
        FakeResolver(RECORDS),
    )
    assert rep.ok, [r.problems for r in rep.rejected]
    assert rep.status == "pass"


@pytest.mark.parametrize(
    ("claim", "problem"),
    [
        (fact("The award is USD 2,000,000.", OPP), "number"),  # invented amount
        (fact("Runway is 20 months.", TOOL), "number"),  # wrong number
        (fact("The score is 0.79.", OPP), "number"),  # outside ±0.5 % of every number in the record
        (fact("The deadline is 2026-12-01.", OPP), "date"),  # wrong date
        (fact("Aurora Ventures Capital will co-invest.", OPP), "entity"),  # invented investor
        (fact("The counterparty is keen.", "opportunity:99999999-9999-9999-9999-999999999999"), "resolve"),
        (fact("It scores 50.0%.", SECRET), "scope"),  # exists but not readable by the caller
        ({"text": "A fact with no citation.", "kind": "fact", "evidence": []}, "cites no evidence"),
        ({"text": "It will probably win.", "kind": "inference", "basis": []}, "no basis"),
    ],
)
async def test_unsupported_claims_are_rejected(claim, problem):
    rep = await check([claim], FakeResolver(RECORDS, out_of_scope=[SECRET]))
    assert not rep.ok and len(rep.rejected) == 1
    assert any(problem in p for p in rep.rejected[0].problems), rep.rejected[0].problems


async def test_inference_with_basis_passes_and_numbers_still_checked():
    ok = {
        "text": "With 14.33 months of runway, a 2026-11-15 decision leaves room.",
        "kind": "inference",
        "basis": [TOOL, OPP],
    }
    bad = {"text": "This lifts runway to 30 months.", "kind": "inference", "basis": [TOOL]}
    rep = await check([ok, bad], FakeResolver(RECORDS))
    assert len(rep.passed) == 1 and len(rep.rejected) == 1


async def test_field_ref_restricts_matching_to_that_field():
    class FieldResolver(FakeResolver):
        async def resolve(self, ref):
            base, _, fld = ref.partition("#")
            rec = self.records.get(base)
            return Resolved(ref, {"field": fld, "value": rec[fld]} if fld else rec, "opportunity") if rec else None

    rep = await check([fact("The score is 0.80.", f"{OPP}#score")], FieldResolver(RECORDS))
    assert not rep.ok, "0.80 is the completeness, not the cited score field"


async def test_quoted_title_numbers_and_years_are_allowed():
    rep = await check([fact("“SBIR Phase II Clean Energy 2027” is open.", OPP)], FakeResolver(RECORDS))
    assert rep.ok


async def test_revisions_then_strip_to_gaps():
    calls = []

    async def revise(report, attempt):
        calls.append((attempt, revision_feedback(report)))
        return [fact("The award is USD 9,999,999.", OPP)] if attempt == 1 else None

    rep = await check_with_revisions([fact("The award is USD 2,000,000.", OPP)], FakeResolver(RECORDS), "t", revise)
    assert [a for a, _ in calls] == [1, 2]
    assert "does not match" in calls[0][1]
    assert rep.revisions == 2 and not rep.passed
    assert rep.gaps and rep.gaps[0].startswith("Unsupported claim removed")


async def test_malformed_claims_counted():
    rep = await check_with_revisions([{"nope": 1}, "text"], FakeResolver(RECORDS), "t")
    assert rep.malformed == 2 and not rep.ok and rep.gaps


def test_number_extraction_units():
    got = {n["text"]: n["candidates"] for n in extract_numbers("74% of $1.2M, 3 of 5, 7.5/100, 2 bn")}
    assert 0.74 in got["74%"] and 1_200_000 in got["$1.2M"] and 2e9 in got["2 bn"] and 0.075 in got["7.5/100"]
    assert org_names("Backed by Northwind Climate Fund I and Blue Ridge Ventures.") == [
        "Northwind Climate Fund I",
        "Blue Ridge Ventures",
    ]


# ----------------------------------------------------------------------------- approval token
KEY = b"k" * 32


def test_token_binds_subject_and_hash():
    s = ApprovalTokenSigner(KEY, 60)
    h = content_hash({"to": "a@b.co", "body": "hi"})
    tok = s.issue("outbox:1", h, "u1", ["u1"])
    assert s.verify(tok.token, subject="outbox:1", digest=h)["jti"] == tok.jti
    with pytest.raises(InvalidApprovalToken, match="hash mismatch"):
        s.verify(tok.token, subject="outbox:1", digest=content_hash({"to": "a@b.co", "body": "edited"}))
    with pytest.raises(InvalidApprovalToken, match="different subject"):
        s.verify(tok.token, subject="outbox:2", digest=h)
    with pytest.raises(InvalidApprovalToken):
        ApprovalTokenSigner(b"x" * 32).verify(tok.token, subject="outbox:1", digest=h)  # forged key


def test_token_expiry_and_key_rules():
    s = ApprovalTokenSigner(KEY, 60)
    now = int(time.time())
    expired = jwt.encode(
        {"iss": "cortex-approval-service", "aud": "cortex-outbox", "sub": "outbox:1", "content_hash": "h", "jti": "j",
         "iat": now - 120, "exp": now - 60},
        KEY, algorithm="HS256",
    )  # fmt: skip
    with pytest.raises(InvalidApprovalToken):
        s.verify(expired, subject="outbox:1", digest="h")
    with pytest.raises(SigningKeyMissing):
        ApprovalTokenSigner(b"short")


def test_content_hash_is_canonical():
    assert content_hash({"a": 1, "b": [1, 2]}) == content_hash({"b": [1, 2], "a": 1})
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_content_flags_select_policies():
    fin = content_flags({"body": "Our valuation cap is 8m with a 20% discount."}, "outbound")
    assert fin["contains_financial_terms"] and required_approvals(fin) == 2
    pii = content_flags({"body": "Call Ada on +44 20 7946 0958"}, "export")
    assert pii["contains_pii"]
    rec = content_flags({"to": "ada@example.org", "body": "Hello"}, "outbound", "ada@example.org")
    assert not rec["contains_pii"], "the recipient address itself isn't PII in the content"
    assert content_flags({}, "submission")["is_grant_submission"]
    dates = content_flags({"body": "Deadline 2026-12-15; amount USD 1,250,000; ref 2026-09-30T10:00:00"}, "export")
    assert not dates["contains_pii"], "dates and amounts are not phone numbers"
    assert content_flags({"body": "(415) 555-0100"}, "export")["contains_pii"]
