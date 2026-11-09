"""SEC-2: the dev realm, its generator, the compose files, docs and scripts carry no credential.

The realm holds Keycloak `${VAR}` placeholders; compose passes each VAR to Keycloak with `:?`, so a stack without it
stops before starting instead of importing a literal. Live values are compared in-process and reported by name only.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

import scripts.smoke as smoke
from tests.unit.test_mysql_schema_versioning import _ComposeLoader

ROOT = Path(__file__).resolve().parents[2]
KEYCLOAK = ROOT / "infra" / "keycloak"
PLACEHOLDER = re.compile(r"^\$\{([A-Z_]+)\}$")
SECRETISH = re.compile(r"PASSWORD|SECRET|TOKEN|TOTP", re.I)


def _generator(monkeypatch, name="realm_under_test"):
    monkeypatch.delenv("SMOKE_TOTP_SECRET", raising=False)
    spec = importlib.util.spec_from_file_location(name, KEYCLOAK / "generate_realm.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _credentials(realm):
    """(where, value) for every client secret and user credential value in a realm."""
    for c in realm["clients"]:
        if "secret" in c:
            yield f"client {c['clientId']}", c["secret"]
    for u in realm["users"]:
        for cred in u.get("credentials", []):
            yield f"user {u['username']} {cred['type']}", cred.get("value", cred.get("secretData"))


def test_generated_realm_holds_only_placeholders_for_every_credential(monkeypatch):
    gen = _generator(monkeypatch)
    assert set(gen.REALM_ENV_VARS) == {
        "SMOKE_USER_PASSWORD",
        "API_CLIENT_SECRET",
        "WORKER_CLIENT_SECRET",
        "INGESTION_CLIENT_SECRET",
    }
    creds = list(_credentials(gen.REALM))
    assert len(creds) == 10  # 3 client secrets + 7 dev-user passwords; no OTP without SMOKE_TOTP_SECRET
    for where, value in creds:
        m = PLACEHOLDER.match(value or "")
        assert m and m[1] in gen.REALM_ENV_VARS, where  # never a value


def test_committed_realm_is_the_generator_output_and_has_no_credential(monkeypatch):
    gen = _generator(monkeypatch, "realm_sync_check")
    text = (KEYCLOAK / "realm-cortex.json").read_text(encoding="utf-8")
    assert json.loads(text) == gen.REALM, "realm-cortex.json is stale: run `make realm` (without SMOKE_TOTP_SECRET)"
    for where, value in _credentials(json.loads(text)):
        assert PLACEHOLDER.match(value or ""), where
    assert set(re.findall(r"\$\{([^}]*)\}", text)) == set(gen.REALM_ENV_VARS)  # no other placeholder is resolved


def test_generator_source_has_no_credential_literal():
    tree = ast.parse((KEYCLOAK / "generate_realm.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            # *_VAR constants hold variable names, not values
            assert not [n for n in names if SECRETISH.search(n) and not n.endswith("_VAR")], names
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in ("secret", "value", "secretData"):
                    assert not (isinstance(v, ast.Constant) and isinstance(v.value, str)), k.value


@pytest.mark.parametrize(
    ("compose_file", "service"),
    [
        ("docker-compose.yml", "keycloak"),
        ("docker-compose.mysql-demo.yml", "keycloak-demo"),
        ("docker-compose.mysql-test.yml", "keycloak-test"),
    ],
)
def test_every_realm_import_requires_each_placeholder_variable(compose_file, service, monkeypatch):
    gen = _generator(monkeypatch, f"realm_{service.replace('-', '_')}")
    svc = yaml.load((ROOT / "infra" / compose_file).read_text(encoding="utf-8"), Loader=_ComposeLoader)["services"][
        service
    ]
    assert any("realm-cortex.json" in v for v in svc["volumes"]), "service no longer imports the realm"
    env = svc["environment"]
    for var in gen.REALM_ENV_VARS:
        assert env.get(var, "").startswith("${" + var + ":?"), (compose_file, var)  # missing -> compose stops


def test_every_compose_file_that_mounts_the_realm_is_covered():
    mounting = sorted(
        p.name
        for p in (ROOT / "infra").glob("docker-compose*.yml")
        if "realm-cortex.json" in p.read_text(encoding="utf-8")
    )
    assert mounting == ["docker-compose.mysql-demo.yml", "docker-compose.mysql-test.yml", "docker-compose.yml"]


def test_no_mysql_root_password_on_a_command_line():
    for path in [*(ROOT / "infra").glob("docker-compose*.yml"), *(ROOT / "infra" / "mysql" / "init").glob("*.sh")]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"""(?<![\w-])-p\s*["']?\$""", text), path.name  # -p$PW / -p"${PW}" shows in `ps`
        assert "--password=$" not in text and '--password="$' not in text, path.name
    init = (ROOT / "infra" / "mysql" / "init" / "01-keycloak.sh").read_text(encoding="utf-8")
    assert 'MYSQL_PWD="${MYSQL_ROOT_PASSWORD}" mysql' in init


def test_scripts_take_the_dev_password_from_the_environment():
    for name in ("contract_live.py", "demo_phase2.py", "demo_phase3.py", "load_test.py"):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "generate_realm" not in text and "DEV_PASSWORD" not in text, name
        assert 'setting("SMOKE_USER_PASSWORD")' in text or "setting('SMOKE_USER_PASSWORD')" in text, name


def test_minio_client_fails_safely_without_a_password(monkeypatch):
    spec = importlib.util.spec_from_file_location("ops_common_under_test", ROOT / "scripts" / "ops_common.py")
    ops = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ops)
    monkeypatch.setattr(ops, "MINIO_PASSWORD", "")
    with pytest.raises(SystemExit, match="MINIO_ROOT_PASSWORD"):
        ops.minio_client()


LIVE = (
    "SMOKE_USER_PASSWORD",
    "SMOKE_TOTP_SECRET",
    "API_CLIENT_SECRET",
    "WORKER_CLIENT_SECRET",
    "INGESTION_CLIENT_SECRET",
    "MINIO_ROOT_PASSWORD",
    "VAULT_DEV_ROOT_TOKEN",
    "GRAFANA_ADMIN_PASSWORD",
    "POSTGRES_PASSWORD",
    "KEYCLOAK_ADMIN_PASSWORD",
    "MYSQL_TEST_PASSWORD",
    "MYSQL_TEST_ROOT_PASSWORD",
    "APPROVAL_SIGNING_KEY",
)
SCANNED = [
    ROOT / "README.md",
    ROOT / ".env.example",
    ROOT / ".gitleaks.toml",
    ROOT / "Makefile",
    ROOT / "make.ps1",
    *(ROOT / "docs").glob("*.md"),
    *(ROOT / "infra").rglob("*.yml"),
    *(ROOT / "infra" / "keycloak").glob("*.*"),
    *(ROOT / "infra" / "mysql").rglob("*.*"),
    *(ROOT / "scripts").glob("*.py"),
    *(ROOT / "apps" / "web" / "e2e").glob("*.ts"),
    *(ROOT / ".github" / "workflows").glob("*.yml"),
    *(ROOT / "tests").rglob("*.py"),
]


def test_no_live_credential_value_in_docs_config_scripts_or_tests():
    """The values set in the environment / git-ignored .env must not appear in any committed-candidate file."""
    values = {n: v for n in LIVE if (v := smoke.setting(n, required=False)) and len(v) >= 6}
    leaks = []
    for path in SCANNED:
        if path.is_file() and path.suffix not in (".pyc",):
            text = path.read_text(encoding="utf-8", errors="replace")
            leaks += [f"{path.relative_to(ROOT)}: {n}" for n, v in values.items() if v in text]
    assert leaks == []  # names only, never values
