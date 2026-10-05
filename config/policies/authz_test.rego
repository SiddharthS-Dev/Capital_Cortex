package cortex.authz_test

import rego.v1

import data.cortex.authz

rbac := {
	"roles": {
		"admin": {"mfa": "required", "clearance": "restricted", "permissions": ["*"]},
		"analyst": {"mfa": "optional", "clearance": "confidential", "permissions": ["opportunity:read", "graph:read"]},
		"auditor": {"mfa": "required", "clearance": "restricted", "permissions": ["audit:read", "audit:verify"]},
		"executive": {"mfa": "required", "clearance": "confidential", "permissions": ["approval:decide"]},
		"service": {"mfa": "none", "clearance": "internal", "permissions": ["signal:write", "system:ping", "graph:write"]},
	},
	"service_clients": {"cortex-ingestion": ["signal:write", "system:ping"]},
	"classifications": ["public", "internal", "confidential", "restricted"],
	"executive_approvable_subjects": ["board_report"],
}

user(roles, mfa) := {"sub": "u1", "roles": roles, "grants": [], "is_service": false, "mfa": mfa}

test_analyst_can_read_opportunities if {
	authz.allow with input as {"subject": user(["analyst"], false), "action": "opportunity:read", "resource": {"type": "opportunity"}}
		with data.rbac as rbac
}

test_analyst_cannot_read_audit if {
	not authz.allow with input as {"subject": user(["analyst"], false), "action": "audit:read", "resource": {"type": "audit_log"}}
		with data.rbac as rbac
}

test_admin_wildcard if {
	authz.allow with input as {"subject": user(["admin"], true), "action": "anything:at_all", "resource": {"type": "x"}}
		with data.rbac as rbac
}

test_admin_without_mfa_denied if {
	not authz.allow with input as {"subject": user(["admin"], false), "action": "opportunity:read", "resource": {"type": "opportunity"}}
		with data.rbac as rbac
}

test_admin_without_mfa_allowed_when_switched_off if {
	authz.allow with input as {"subject": user(["admin"], false), "action": "opportunity:read", "resource": {"type": "opportunity"}}
		with data.rbac as rbac
		with opa.runtime as {"env": {"CORTEX_MFA_REQUIRED": "false"}}
}

test_auditor_verify_with_mfa if {
	authz.allow with input as {"subject": user(["auditor"], true), "action": "audit:verify", "resource": {"type": "audit_log"}}
		with data.rbac as rbac
}

test_classification_above_clearance_denied if {
	not authz.allow with input as {"subject": user(["analyst"], false), "action": "opportunity:read", "resource": {"type": "document", "classification": "restricted"}}
		with data.rbac as rbac
}

test_classification_within_clearance_allowed if {
	authz.allow with input as {"subject": user(["analyst"], false), "action": "opportunity:read", "resource": {"type": "document", "classification": "confidential"}}
		with data.rbac as rbac
}

test_service_client_scoped if {
	svc := {"sub": "s", "roles": ["service"], "grants": [], "is_service": true, "client_id": "cortex-ingestion", "mfa": false}
	authz.allow with input as {"subject": svc, "action": "signal:write", "resource": {"type": "signal"}} with data.rbac as rbac
	not authz.allow with input as {"subject": svc, "action": "graph:write", "resource": {"type": "graph"}} with data.rbac as rbac
}

test_unknown_service_client_denied if {
	svc := {"sub": "s", "roles": ["service"], "grants": [], "is_service": true, "client_id": "rogue", "mfa": false}
	not authz.allow with input as {"subject": svc, "action": "system:ping", "resource": {"type": "system"}} with data.rbac as rbac
}

test_executive_board_report_only if {
	authz.allow with input as {"subject": user(["executive"], true), "action": "approval:decide", "resource": {"type": "approval", "subject_type": "board_report"}}
		with data.rbac as rbac
	not authz.allow with input as {"subject": user(["executive"], true), "action": "approval:decide", "resource": {"type": "approval", "subject_type": "outbox"}}
		with data.rbac as rbac
}

# A second role without approval:decide must not lift the executive narrowing (was `roles == ["executive"]`).
test_executive_plus_other_role_still_board_report_only if {
	not authz.allow with input as {"subject": user(["analyst", "executive"], true), "action": "approval:decide", "resource": {"type": "approval", "subject_type": "outbox"}}
		with data.rbac as rbac
}

test_executive_plus_admin_decides_anything if {
	authz.allow with input as {"subject": user(["admin", "executive"], true), "action": "approval:decide", "resource": {"type": "approval", "subject_type": "outbox"}}
		with data.rbac as rbac
}

test_raw_cypher_admin_only if {
	r := {"roles": {"analyst": {"mfa": "optional", "clearance": "confidential", "permissions": ["graph:*"]}}, "classifications": ["public"], "service_clients": {}}
	not authz.allow with input as {"subject": user(["analyst"], false), "action": "graph:cypher", "resource": {"type": "graph"}} with data.rbac as r
}

test_pii_export_denied if {
	not authz.allow with input as {"subject": user(["admin"], true), "action": "contact:export", "resource": {"type": "contact", "contains_pii": true, "export": true}}
		with data.rbac as rbac
}
