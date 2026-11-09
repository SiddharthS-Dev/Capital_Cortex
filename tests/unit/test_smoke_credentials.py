"""SEC-1: the smoke workflow takes its credentials from the environment / .env, never from committed code.

Only test-only values are used here (the TOTP vectors use the RFC 6238 published test key).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CRED_VARS = (
    "SMOKE_USER_PASSWORD",
    "SMOKE_TOTP_SECRET",
    "WORKER_CLIENT_SECRET",
    "GRAFANA_PASSWORD",
    "GRAFANA_ADMIN_PASSWORD",
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def smoke(monkeypatch, tmp_path):
    for v in CRED_VARS:
        monkeypatch.delenv(v, raising=False)
    mod = _load(ROOT / "scripts" / "smoke.py", "smoke_under_test")
    monkeypatch.setattr(mod, "ENV_FILE", tmp_path / ".env")  # isolated from the developer's real .env
    return mod


def test_setting_prefers_environment_then_dotenv(smoke, monkeypatch):
    smoke.ENV_FILE.write_text('SMOKE_TOTP_SECRET="from-dotenv-test-only"\n', encoding="utf-8")
    assert smoke.setting("SMOKE_TOTP_SECRET") == "from-dotenv-test-only"
    monkeypatch.setenv("SMOKE_TOTP_SECRET", "from-env-test-only")
    assert smoke.setting("SMOKE_TOTP_SECRET") == "from-env-test-only"


def test_missing_credential_fails_with_its_name_and_no_value(smoke, capsys):
    smoke.ENV_FILE.write_text("UNRELATED=value-must-not-leak\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        smoke.setting("SMOKE_TOTP_SECRET")
    msg = str(e.value)
    assert "SMOKE_TOTP_SECRET" in msg and "value-must-not-leak" not in msg
    assert smoke.setting("GRAFANA_PASSWORD", required=False) is None
    assert capsys.readouterr().out == ""


def test_smoke_stops_before_any_request_when_the_totp_seed_is_missing(smoke, monkeypatch, capsys):
    monkeypatch.setenv("SMOKE_USER_PASSWORD", "test-only-password")
    monkeypatch.setenv("WORKER_CLIENT_SECRET", "test-only-worker-secret")

    def no_network(*a, **k):
        raise AssertionError("smoke made a request before checking its credentials")

    monkeypatch.setattr(smoke.httpx, "Client", no_network)
    monkeypatch.setattr(smoke.httpx, "post", no_network)
    with pytest.raises(SystemExit, match="SMOKE_TOTP_SECRET"):
        smoke.main()
    out = capsys.readouterr().out
    assert "test-only-password" not in out and "test-only-worker-secret" not in out


def test_totp_matches_rfc6238_vectors(smoke):
    key = b"12345678901234567890"  # RFC 6238 Appendix B test key (SHA-1)
    assert smoke.totp(key, t=59) == "287082"
    assert smoke.totp(key, t=1111111109) == "081804"


def test_smoke_script_has_no_credential_literals():
    tree = ast.parse((ROOT / "scripts" / "smoke.py").read_text(encoding="utf-8"))
    secretish = re.compile(r"PASSWORD|SECRET|TOTP|_PW$", re.I)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            assert not any(secretish.search(n) for n in names), names
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "get" and len(node.args) == 2:
            key = node.args[0]
            if isinstance(key, ast.Constant) and isinstance(key.value, str) and secretish.search(key.value):
                raise AssertionError(f"os.environ.get({key.value!r}, <default>) falls back to a literal")


def test_realm_generator_writes_an_otp_credential_only_from_the_environment(monkeypatch):
    path = ROOT / "infra" / "keycloak" / "generate_realm.py"

    def smoke_auditor_otp(mod):
        user = next(u for u in mod.REALM["users"] if u["username"] == "smoke-auditor")
        return [c for c in user["credentials"] if c["type"] == "otp"]

    monkeypatch.delenv("SMOKE_TOTP_SECRET", raising=False)
    mod = _load(path, "realm_no_seed")
    assert mod.SMOKE_TOTP_SECRET is None and smoke_auditor_otp(mod) == []
    monkeypatch.setenv("SMOKE_TOTP_SECRET", "per-run-test-only-seed")
    mod = _load(path, "realm_with_seed")
    (otp,) = smoke_auditor_otp(mod)
    assert json.loads(otp["secretData"])["value"] == "per-run-test-only-seed"
    sys.modules.pop("realm_no_seed", None)
    sys.modules.pop("realm_with_seed", None)


def test_committed_realm_and_e2e_helpers_carry_no_totp_seed():
    realm = json.loads((ROOT / "infra" / "keycloak" / "realm-cortex.json").read_text(encoding="utf-8"))
    assert not [c for u in realm["users"] for c in u.get("credentials", []) if c.get("type") == "otp"]
    helpers = (ROOT / "apps" / "web" / "e2e" / "helpers.ts").read_text(encoding="utf-8")
    assert not re.search(r'(SMOKE_TOTP_SECRET|DEV_PASSWORD)\s*=\s*"', helpers)
    assert 'requiredEnv("SMOKE_TOTP_SECRET")' in helpers and 'requiredEnv("SMOKE_USER_PASSWORD")' in helpers
