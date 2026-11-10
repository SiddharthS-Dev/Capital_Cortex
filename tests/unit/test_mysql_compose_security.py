"""MySQL compose hardening: no fallback secrets, loopback-only port by default, private production overlay.

`docker compose config` itself is exercised in the readiness report; these checks keep the files from regressing
without needing Docker.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

import scripts.smoke as smoke
from tests.unit.test_mysql_schema_versioning import _ComposeLoader

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"
SECRET_VAR = re.compile(r"\$\{(?P<name>[A-Z_]*(?:PASSWORD|SECRET|TOKEN|SIGNING_KEY)[A-Z_]*)(?P<op>:-|:\?|-|\?)?[^}]*\}")


def _load(name: str) -> dict:
    return yaml.load((INFRA / name).read_text(encoding="utf-8"), Loader=_ComposeLoader)


def test_mysql_overlay_has_no_fallback_secrets():
    text = (INFRA / "docker-compose.mysql.yml").read_text(encoding="utf-8")
    refs = [(m["name"], m["op"]) for m in SECRET_VAR.finditer(text)]
    assert refs, "expected secret references"
    # MYSQL_APP_PASSWORD may be empty: its fallback is the required ${MYSQL_PASSWORD:?}, never a literal
    assert [r for r in refs if r[1] != ":?" and r[0] != "MYSQL_APP_PASSWORD"] == []
    assert "${MYSQL_APP_PASSWORD:-${MYSQL_PASSWORD:?" in text
    assert {n for n, _ in refs} >= {"MYSQL_ROOT_PASSWORD", "MYSQL_PASSWORD", "MINIO_ROOT_PASSWORD"}
    for old in ("cortex-pw", "cortex_root_pw"):  # retired dev literals (already public in history)
        assert old not in text
    live = smoke.setting("MINIO_ROOT_PASSWORD", required=False)  # from the environment or .env, never a literal here
    assert not (live and live in text), "MINIO_ROOT_PASSWORD value is in the overlay"


def test_every_mysql_database_url_requires_the_password():
    compose = _load("docker-compose.mysql.yml")
    for svc in ("migrate", "api", "worker"):
        url = compose["services"][svc]["environment"]["DATABASE_URL"]
        assert url.startswith("mysql+asyncmy://") and "${MYSQL_PASSWORD:?" in url
    assert compose["services"]["keycloak"]["environment"]["KC_DB_PASSWORD"].startswith("${MYSQL_PASSWORD:?")


def test_mysql_port_is_loopback_by_default_and_healthcheck_hides_root_password():
    mysql = _load("docker-compose.mysql.yml")["services"]["mysql"]
    assert mysql["ports"] == ["${MYSQL_BIND_ADDRESS:-127.0.0.1}:${MYSQL_PORT:-53306}:3306"]
    probe = " ".join(mysql["healthcheck"]["test"])
    assert "-p$$" not in probe and "MYSQL_PWD=" in probe
    test_stack = _load("docker-compose.mysql-test.yml")["services"]["mysql-test"]
    assert all(p.startswith("127.0.0.1:") for p in test_stack["ports"])


def test_test_and_demo_stacks_require_secrets_and_hide_the_root_password():
    """The local test/demo stacks used to fall back to committed dev passwords and to pass the root password on the
    healthcheck command line (visible in the process list)."""
    for name in ("docker-compose.mysql-test.yml", "docker-compose.mysql-demo.yml"):
        text = (INFRA / name).read_text(encoding="utf-8")
        refs = [(m["name"], m["op"]) for m in SECRET_VAR.finditer(text)]
        assert refs and [r for r in refs if r[1] != ":?"] == [], name
        # the live values (tests/conftest.py loads them from the git-ignored .env); no credential literal in this file
        for var in ("MYSQL_TEST_PASSWORD", "MYSQL_TEST_ROOT_PASSWORD", "KEYCLOAK_ADMIN_PASSWORD"):
            assert not (os.environ.get(var) and os.environ[var] in text), (name, var)
    mysql = _load("docker-compose.mysql-test.yml")["services"]["mysql-test"]
    probe = " ".join(mysql["healthcheck"]["test"])
    assert "-p$$" not in probe and "MYSQL_PWD=" in probe
    # triggers can be created by the schema-level `cortex` account (infra/mysql/least_privilege.sql), no SUPER needed
    assert "--log-bin-trust-function-creators=1" in mysql["command"]


def test_postgres_rollback_stack_requires_its_database_and_keycloak_secrets():
    """SEC-4/SEC-2: the PostgreSQL stack (kept for the rollback window) no longer falls back to the publicly committed
    dev credentials: every secret variable is required (`:?`, compose stops with the name), none has a default, and
    .env.example carries empty placeholders."""
    text = (INFRA / "docker-compose.yml").read_text(encoding="utf-8")
    refs = [(m["name"], m["op"]) for m in SECRET_VAR.finditer(text)]
    # no secret has a non-empty default (`${X:-}` is empty: APPROVAL_SIGNING_KEY fails closed without a value;
    # KC_DB_PASSWORD's default is the required ${POSTGRES_PASSWORD:?})
    with_value = [m["name"] for m in SECRET_VAR.finditer(text) if m["op"] == ":-" and not m.group(0).endswith(":-}")]
    assert with_value == ["KC_DB_PASSWORD"], with_value
    for name in (
        "POSTGRES_PASSWORD",
        "KEYCLOAK_ADMIN_PASSWORD",
        "MINIO_ROOT_PASSWORD",
        "VAULT_DEV_ROOT_TOKEN",
        "GRAFANA_ADMIN_PASSWORD",
        "WORKER_CLIENT_SECRET",
    ):
        ops = {op for n, op in refs if n == name}
        assert ops == {":?"}, (name, ops)
    example = dict(
        line.split("=", 1)
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    secretish = re.compile(r"PASSWORD|SECRET|TOKEN|_KEY$")
    assert {k: v for k, v in example.items() if secretish.search(k) and v} == {}  # every credential is empty
    for name in ("API_CLIENT_SECRET", "INGESTION_CLIENT_SECRET", "SMOKE_USER_PASSWORD", "SMOKE_TOTP_SECRET"):
        assert example[name] == "", name  # documented, empty


def test_least_privilege_script_revokes_global_and_keeps_schema_grants():
    sql = (INFRA / "mysql" / "least_privilege.sql").read_text(encoding="utf-8")
    body = " ".join(ln.strip() for ln in sql.splitlines() if ln.strip() and not ln.strip().startswith("--"))
    code = [c.strip() for c in body.split(";") if c.strip()]
    assert "REVOKE ALL PRIVILEGES ON *.* FROM 'cortex'@'%'" in code
    grants = [c for c in code if c.startswith("GRANT")]
    assert grants and all(" ON *.* " not in g for g in grants)  # nothing server-wide is granted back
    assert {"`cortex`.*", "`keycloak`.*", "`cortex\\_%`.*"} == {g.split(" ON ")[1].split(" TO ")[0] for g in grants}


def test_private_overlay_publishes_no_mysql_port_and_requires_app_secrets():
    text = (INFRA / "docker-compose.mysql-private.yml").read_text(encoding="utf-8")
    assert "ports: !reset []" in text
    compose = _load("docker-compose.mysql-private.yml")
    assert compose["services"]["mysql"]["ports"] == []
    refs = {m["name"]: m["op"] for m in SECRET_VAR.finditer(text)}
    for name in (
        "MINIO_ROOT_PASSWORD",
        "KEYCLOAK_ADMIN_PASSWORD",
        "APPROVAL_SIGNING_KEY",
        "WORKER_CLIENT_SECRET",
        "GRAFANA_ADMIN_PASSWORD",
    ):
        assert refs.get(name) == ":?", name
    worker = compose["services"]["worker"]["environment"]
    assert worker["KEYCLOAK_ADMIN_PASSWORD"].startswith("${KEYCLOAK_ADMIN_PASSWORD:?")


def test_env_example_documents_mysql_secrets_without_values():
    lines = dict(
        line.split("=", 1)
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    for name in (
        "MYSQL_ROOT_PASSWORD",
        "MYSQL_PASSWORD",
        "MYSQL_BACKUP_ENCRYPTION_KEY",
        "MYSQL_BACKUP_S3_SECRET_KEY",
        "MIGRATION_PG_PASSWORD",
        "MIGRATION_MYSQL_PASSWORD",
    ):
        assert lines.get(name) == "", name
    assert lines["MYSQL_BIND_ADDRESS"] == "127.0.0.1"
