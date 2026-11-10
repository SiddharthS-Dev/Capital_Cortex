# Capital Cortex: Production Readiness Checklist

Assessed 2026-11-03. **Local demo results do not count toward production readiness.** Every item below needs evidence from the production environment, which does not exist yet (D-011: provider and host undecided; Terraform is a stub).

Statuses: PASS · FAIL · BLOCKED · NOT STARTED · REQUIRES APPROVAL

| # | Item | Status | Evidence / gap | Owner |
|---|---|---|---|---|
| 1 | Production MySQL infrastructure | **BLOCKED** | No host, provider or size (B2, INFRA-1). The buffer pool must cover the working set (≥4 GB for about 3 GB of data). | DevOps |
| 2 | Network isolation | **NOT STARTED** | `infra/docker-compose.mysql-private.yml` (no published DB port) exists as a template; no production network | DevOps |
| 3 | Database encryption (TLS in transit, at rest) | **NOT STARTED** | Client TLS verification exists for migration tooling (`test_secure_connect.py` passes); no production TLS, no at-rest encryption configured | DevOps |
| 4 | Backup encryption and key custody | **FAIL** | `backup_mysql.py` supports AES-256-GCM, but **no key exists**; today's demo backup relies on Windows EFS; key custody is undefined | DevOps + security |
| 5 | Off-site backup | **NOT STARTED** | The S3-compatible destination is supported by the tool; no approved store | DevOps |
| 6 | Point-in-time recovery | **NOT STARTED** | No binlog retention or shipping design for production MySQL | DBA |
| 7 | Backup restore rehearsal | **PASS (demo only) / NOT STARTED (production)** | Demo: both databases restored into isolated databases with zero row-count drift. Production: none. | DBA |
| 8 | Monitoring and alerting | **NOT STARTED** | OTel/Prometheus/Grafana/Loki in the dev stack; `cortex.security` events emitted; no production alert rules or SIEM | DevOps |
| 9 | Keycloak HTTPS/TLS | **FAIL** | Keycloak runs `start-dev` over HTTP in every compose file | DevOps |
| 10 | Vault/KMS | **FAIL** | Vault is in dev mode (in-memory, root token); no production secret store | DevOps |
| 11 | Secret rotation | **REQUIRES APPROVAL** | Credentials exposed in public git history are not yet rotated (`docs/SECURITY_CREDENTIAL_ROTATION_RUNBOOK.md`) | You |
| 12 | PostgreSQL production backup | **BLOCKED** | No authorised production dump or checksums (B1) | DevOps → DBA |
| 13 | Cutover approval | **REQUIRES APPROVAL** | B3 not given; it needs ARCH-3 | Project Lead |
| 14 | Maintenance window | **NOT STARTED** | Not scheduled | Project Lead |
| 15 | Rollback plan | **BLOCKED** | It depends on the ARCH-3 decision (no reverse sync) | Project Lead |
| 16 | Stakeholder communication | **NOT STARTED** | No communications plan | Project Lead |

**Summary:**
- 1 PASS (demo-only restore rehearsal).
- 3 FAIL: backup key custody, Keycloak TLS, Vault/KMS.
- 3 BLOCKED (items 1, 12, 15), 7 NOT STARTED (items 2, 3, 5, 6, 8, 14, 16) and 2 REQUIRES APPROVAL (items 11, 13); item 7 is also not started for production.

**Production readiness: not ready.**

Additional security prerequisites from the enterprise security review §15 (all REQUIRES APPROVAL):
- a DML-only runtime database account;
- Redis authentication;
- container recreation for the hardening;
- applying the Keycloak realm events and lockout;
- npm major upgrades;
- a green CI.
