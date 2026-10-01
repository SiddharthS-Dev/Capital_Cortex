# Governed actuation (I3, SyRS §11/§12). The L7 approval service and outbox sender evaluate
# data.cortex.governance.release. `allow` is true only when no deny rule fires.
# Input:
#   action:    {kind: "outbound"|"submission"|"share_link"|"export", channel, subject_type, recipient_external}
#   content:   {hash, contains_financial_terms, contains_pii, is_grant_submission}
#   approvals: [{approver, roles[], grants[], decision, content_hash, mfa}]
#   requested_by: the principal that asked for approval
#   now:       {weekday (1=Mon..7=Sun), hour (0-23, org local time)}
#   config:    {business_hours_only: bool, allow_self_approval: bool}
package cortex.governance

import rego.v1

default allow := false

allow if count(deny) == 0

# An approval counts only for the exact content hash and with MFA. MFA can be switched off for a local
# environment with CORTEX_MFA_REQUIRED=false in OPA's env (D-033), matching cortex.authz.
mfa_enforced if not opa.runtime().env.CORTEX_MFA_REQUIRED == "false"

mfa_ok(a) if a.mfa == true

mfa_ok(_) if not mfa_enforced

approved := [a |
	some a in input.approvals
	a.decision == "approved"
	a.content_hash == input.content.hash
	mfa_ok(a)
	not self_approval(a)
]

# Segregation of duties: the requester's own approval never counts unless configured (single-person orgs).
self_approval(a) if {
	a.approver == input.requested_by
	not input.config.allow_self_approval
}

approver_roles contains r if {
	some a in approved
	some r in a.roles
}

distinct_approvers := {a.approver | some a in approved}

# outbound_requires_approval
deny contains "outbound_requires_approval" if {
	input.action.kind in {"outbound", "submission", "share_link", "export"}
	count(approved) == 0
}

# financial_terms_require_admin_and_legal
deny contains "financial_terms_require_admin_and_legal" if {
	input.content.contains_financial_terms
	not "admin" in approver_roles
}

deny contains "financial_terms_require_admin_and_legal" if {
	input.content.contains_financial_terms
	not legal_approved
}

legal_approved if {
	some a in approved
	"auditor" in a.roles
	"approver" in a.roles
}

legal_approved if {
	some a in approved
	"compliance:review" in object.get(a, "grants", [])
}

# grant_submission_requires_two_approvers
deny contains "grant_submission_requires_two_approvers" if {
	input.content.is_grant_submission
	count(distinct_approvers) < 2
}

# no_external_send_outside_business_hours (optional, config-driven)
deny contains "no_external_send_outside_business_hours" if {
	input.config.business_hours_only
	input.action.recipient_external
	not within_business_hours
}

within_business_hours if {
	input.now.weekday <= 5
	input.now.hour >= 8
	input.now.hour < 18
}

# self_approval_denied: reported so the approver sees why their decision didn't count
deny contains "self_approval_denied" if {
	some a in input.approvals
	a.decision == "approved"
	a.content_hash == input.content.hash
	self_approval(a)
	count(approved) == 0
}

# pii_export_denied
deny contains "pii_export_denied" if {
	input.action.kind == "export"
	input.content.contains_pii
}
