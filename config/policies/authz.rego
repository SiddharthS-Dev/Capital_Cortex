# Per-request authorisation (I4). Input:
#   subject:  {sub, roles[], grants[], is_service, client_id, mfa}
#   action:   "<resource>:<verb>"
#   resource: {type, id, owner_id, classification, capital_class, ...}
#   context:  {method, path, time}
# data.rbac comes from config/roles.yaml (mounted as /policies/rbac/data.yaml).
package cortex.authz

import rego.v1

default allow := false

allow if {
	rbac_allows
	count(deny) == 0
}

# ---------- RBAC ----------
granted contains p if {
	some role in input.subject.roles
	some p in data.rbac.roles[role].permissions
}

granted contains p if some p in input.subject.grants

matches(g, _) if g == "*"

matches(g, want) if g == want

matches(g, want) if {
	endswith(g, ":*")
	split(want, ":")[0] == trim_suffix(g, ":*")
}

rbac_allows if {
	some g in granted
	matches(g, input.action)
	service_scope_ok
}

service_scope_ok if not input.subject.is_service

service_scope_ok if {
	input.subject.is_service
	some g in data.rbac.service_clients[input.subject.client_id]
	matches(g, input.action)
}

# ---------- MFA (R5) ----------
mfa_required_role if {
	some role in input.subject.roles
	data.rbac.roles[role].mfa == "required"
}

# MFA can be switched off for a local environment with CORTEX_MFA_REQUIRED=false in OPA's env (D-033).
mfa_enforced if not opa.runtime().env.CORTEX_MFA_REQUIRED == "false"

deny contains "mfa_required" if {
	mfa_enforced
	not input.subject.is_service
	mfa_required_role
	not input.subject.mfa
}

# ---------- ABAC: classification clearance ----------
rank(level) := i if {
	some i, l in data.rbac.classifications
	l == level
}

clearance_rank := max({r |
	some role in input.subject.roles
	r := rank(data.rbac.roles[role].clearance)
})

deny contains "classification_exceeds_clearance" if {
	input.resource.classification
	rank(input.resource.classification) > clearance_rank
}

# ---------- executives approve only allowed subject types ----------
deny contains "executive_cannot_approve_subject" if {
	input.action == "approval:decide"
	input.subject.roles == ["executive"]
	not input.resource.subject_type in data.rbac.executive_approvable_subjects
}

# ---------- raw Cypher is admin-only (§8 /graph/query) ----------
deny contains "raw_cypher_admin_only" if {
	input.action == "graph:cypher"
	not "admin" in input.subject.roles
}

# ---------- PII export (pii_export_denied) ----------
deny contains "pii_export_denied" if {
	input.resource.contains_pii == true
	input.resource.export == true
}
