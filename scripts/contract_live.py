"""Live contract test: schemathesis over every GET operation of the running API with a real dev token.

Read-only on purpose (no generated writes land in the database). Writes are covered by the integration tests
(tests/integration) and the authz matrix. Usage: python scripts/contract_live.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "infra" / "keycloak"))
from devtoken import token  # noqa: E402
from generate_realm import DEV_PASSWORD  # noqa: E402

API = os.environ.get("API", "http://localhost:8300")


def main() -> int:
    tok = token("dev-analyst", DEV_PASSWORD)
    exe = Path(sys.executable).with_name("schemathesis.exe" if os.name == "nt" else "schemathesis")
    cmd = [str(exe), "run", f"{API}/v1/openapi.json", "-H", f"Authorization: Bearer {tok}", "--include-method", "GET",
           "--max-examples", "5", "--checks", "not_a_server_error,status_code_conformance,content_type_conformance,response_schema_conformance",
           "--exclude-path-regex", "stream|share"]  # fmt: skip
    return subprocess.call(cmd, env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})  # noqa: S603 - fixed argv


if __name__ == "__main__":
    sys.exit(main())
