package cortex.governance_test

import rego.v1

import data.cortex.governance

approval(who, roles, h) := {"approver": who, "roles": roles, "decision": "approved", "content_hash": h, "mfa": true}

base := {
	"action": {"kind": "outbound", "channel": "email", "recipient_external": true},
	"content": {"hash": "h1", "contains_financial_terms": false, "contains_pii": false, "is_grant_submission": false},
	"approvals": [],
	"now": {"weekday": 2, "hour": 10},
	"config": {"business_hours_only": false},
}

test_outbound_without_approval_denied if {
	not governance.allow with input as base
	"outbound_requires_approval" in governance.deny with input as base
}

test_outbound_with_approval_allowed if {
	governance.allow with input as object.union(base, {"approvals": [approval("a", ["approver"], "h1")]})
}

test_approval_for_other_hash_does_not_count if {
	not governance.allow with input as object.union(base, {"approvals": [approval("a", ["approver"], "OLD")]})
}

test_approval_without_mfa_does_not_count if {
	a := object.union(approval("a", ["approver"], "h1"), {"mfa": false})
	not governance.allow with input as object.union(base, {"approvals": [a]})
}

test_financial_terms_need_admin_and_legal if {
	fin := object.union(base, {"content": object.union(base.content, {"contains_financial_terms": true})})
	not governance.allow with input as object.union(fin, {"approvals": [approval("a", ["approver"], "h1")]})
	governance.allow with input as object.union(fin, {"approvals": [
		approval("f", ["admin", "approver"], "h1"),
		approval("l", ["auditor", "approver"], "h1"),
	]})
}

# One person holding admin and a legal role/grant can't be both halves of "Admin + Legal".
test_financial_terms_admin_and_legal_must_be_two_people if {
	fin := object.union(base, {"content": object.union(base.content, {"contains_financial_terms": true})})
	solo := object.union(approval("f", ["admin", "auditor", "approver"], "h1"), {"grants": ["compliance:review"]})
	not governance.allow with input as object.union(fin, {"approvals": [solo]})
	"financial_terms_require_admin_and_legal" in governance.deny with input as object.union(fin, {"approvals": [solo]})
	governance.allow with input as object.union(fin, {"approvals": [solo, approval("l", ["auditor", "approver"], "h1")]})
}

test_grant_submission_two_approvers if {
	g := object.union(base, {"content": object.union(base.content, {"is_grant_submission": true})})
	not governance.allow with input as object.union(g, {"approvals": [approval("a", ["approver"], "h1")]})
	governance.allow with input as object.union(g, {"approvals": [approval("a", ["approver"], "h1"), approval("b", ["approver"], "h1")]})
}

test_business_hours_optional if {
	night := object.union(base, {"now": {"weekday": 2, "hour": 23}, "approvals": [approval("a", ["approver"], "h1")]})
	governance.allow with input as night
	not governance.allow with input as object.union(night, {"config": {"business_hours_only": true}})
}

test_pii_export_denied if {
	x := object.union(base, {
		"action": {"kind": "export", "channel": "portal_export", "recipient_external": false},
		"content": object.union(base.content, {"contains_pii": true}),
		"approvals": [approval("a", ["admin", "approver"], "h1")],
	})
	not governance.allow with input as x
}

test_self_approval_does_not_count if {
	x := object.union(base, {"requested_by": "a", "approvals": [approval("a", ["approver"], "h1")]})
	not governance.allow with input as x
	"self_approval_denied" in governance.deny with input as x
	governance.allow with input as object.union(x, {"config": {"business_hours_only": false, "allow_self_approval": true}})
}

test_other_approver_counts_when_requester_also_approved if {
	x := object.union(base, {"requested_by": "a", "approvals": [
		approval("a", ["approver"], "h1"),
		approval("b", ["approver"], "h1"),
	]})
	governance.allow with input as x
}

test_mfa_can_be_disabled_for_local_dev if {
	a := object.union(approval("b", ["approver"], "h1"), {"mfa": false})
	governance.allow with input as object.union(base, {"approvals": [a]})
		with opa.runtime as {"env": {"CORTEX_MFA_REQUIRED": "false"}}
}
