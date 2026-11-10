"""scripts/verify_mysql_runtime.py (DATA-2): valid stage, a clean full run, self-cleanup, and no collateral deletes.

The full run executes the script as a subprocess against the configured MySQL test database (MYSQL_TEST_*), which
must be at the migration head (e.g. cortex_unit): the script writes the current stage vocabulary.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from platform_core.db.session import get_mysql_test_url

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_mysql_runtime.py"


def _script():
    spec = importlib.util.spec_from_file_location("verify_mysql_runtime", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # no side effects at import: configure() only runs under __main__
    return mod


def _baseline_stages() -> list[str]:
    schema = (ROOT / "scripts" / "schema_mysql.sql").read_text(encoding="utf-8")
    m = re.search(r"pipeline_stage ENUM\(([^)]*)\)", schema)
    return re.findall(r"'([^']*)'", m.group(1))


def test_verification_stage_is_in_the_current_vocabulary():
    mod = _script()
    assert mod.VERIFY_STAGE in _baseline_stages()
    assert mod.VERIFY_STAGE != "screening"


def test_importing_the_script_does_not_reconfigure_the_process():
    before = {k: os.environ.get(k) for k in ("DATABASE_URL", "REDIS_URL", "CORTEX_ENV")}
    _script()
    assert {k: os.environ.get(k) for k in before} == before


@pytest.fixture
def db():
    eng = create_engine(get_mysql_test_url(driver="pymysql"))
    yield eng
    eng.dispose()


def _sentinel(db) -> str:
    """An unrelated row that looks exactly like the script's own (same title, provenance, demo flag)."""
    sid = str(uuid.uuid4())
    with db.begin() as c:
        c.execute(
            text(
                "INSERT INTO opportunity (id, org_id, title, class, status, pipeline_stage, source_ref, is_demo) "
                "VALUES (:id, '00000000-0000-0000-0000-000000000001', 'Clean Energy Expansion Grant', 'grant', 'active', "
                "'qualified', CAST(:src AS JSON), 1)"
            ),
            {"id": sid, "src": json.dumps({"origin": "runtime_verification"})},
        )
    return sid


def test_cleanup_only_deletes_the_ids_it_is_given(db):
    import asyncio

    mod = _script()
    sid = _sentinel(db)
    try:
        removed = asyncio.run(
            mod.cleanup_verification_records(
                get_mysql_test_url(driver="asyncmy"), {"opportunity": [str(uuid.uuid4())], "organization": []}
            )
        )
        assert removed == {"opportunity": 0}
        with db.connect() as c:
            assert c.execute(text("SELECT COUNT(*) FROM opportunity WHERE id = :id"), {"id": sid}).scalar() == 1
    finally:
        with db.begin() as c:
            c.execute(text("DELETE FROM opportunity WHERE id = :id"), {"id": sid})  # the test's own row


def test_full_run_succeeds_cleans_up_its_rows_and_keeps_unrelated_ones(db):
    sid = _sentinel(db)
    try:
        env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
        env["PYTHONUTF8"] = "1"
        run = subprocess.run(
            [sys.executable, str(SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300
        )
        assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
        assert "ALL RUNTIME VERIFICATION CHECKS PASSED" in run.stdout
        created = json.loads(next(ln for ln in run.stdout.splitlines() if ln.startswith("CREATED_IDS "))[12:])
        assert sum(len(v) for v in created.values()) == 6
        with db.connect() as c:
            for table, ids in created.items():
                for row_id in ids:
                    n = c.execute(text(f"SELECT COUNT(*) FROM `{table}` WHERE id = :id"), {"id": row_id}).scalar()
                    assert n == 0, f"{table} {row_id} left behind"
            assert c.execute(text("SELECT COUNT(*) FROM opportunity WHERE id = :id"), {"id": sid}).scalar() == 1
    finally:
        with db.begin() as c:
            c.execute(text("DELETE FROM opportunity WHERE id = :id"), {"id": sid})
