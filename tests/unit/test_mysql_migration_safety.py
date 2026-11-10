"""AUD-5, AUD-6, AUD-8, AUD-10: migration reproducibility, dependency pins, eval gate and session time zone."""

from __future__ import annotations

import configparser
import hashlib
import importlib.util
import re
import shutil
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from cortex.l8_actuation.api.routers import graph as graph_router
from platform_core import db as db_pkg
from platform_core.db import session as session_mod
from platform_core.errors import Problem

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "migrations_mysql" / "baseline" / "m0001_schema.sql"
BASELINE_SHA256 = "2426845c4ef7d27f7055c07f9512187fbbb275848bc495a933ce639f53715ecd"


def _norm(p: Path) -> bytes:
    return p.read_bytes().replace(b"\r\n", b"\n")


def test_baseline_is_frozen():
    assert hashlib.sha256(_norm(BASELINE)).hexdigest() == BASELINE_SHA256, (
        "applied baseline changed: add a new revision instead"
    )


@pytest.mark.parametrize("rev", ["m0001_mysql_baseline.py", "m0004_reconcile_legacy_layouts.py"])
def test_revisions_read_only_the_frozen_baseline(rev):
    src = (ROOT / "migrations_mysql" / "versions" / rev).read_text(encoding="utf-8")
    assert re.search(r'SCHEMA_FILE = .*"baseline" / "m0001_schema.sql"', src)
    assert '"scripts" / "schema_mysql.sql"' not in src


def test_history_is_linear_and_ends_at_m0004():
    cfg = Config(str(ROOT / "alembic.ini"))  # default section
    cfg.set_main_option("script_location", str(ROOT / "migrations_mysql"))
    sd = ScriptDirectory.from_config(cfg)
    assert sd.get_heads() == ["m0004_reconcile_legacy_layouts"]
    assert [r.revision for r in sd.walk_revisions()][-1] == "m0001_mysql_baseline"


def test_baseline_holds_the_expected_tables():
    tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS `?([a-z_]+)`?", BASELINE.read_text(encoding="utf-8")))
    assert len(tables) == 49 and "audit_lock" in tables


def test_postgres_history_refuses_a_mysql_url():
    assert 'if not url.startswith("postgresql")' in (ROOT / "migrations" / "env.py").read_text(encoding="utf-8")


def test_default_alembic_section_is_mysql():
    ini = configparser.ConfigParser()
    ini.read(ROOT / "alembic.ini")
    assert ini["alembic"]["script_location"] == "migrations_mysql"


@pytest.mark.parametrize("pkg", ["asyncmy", "aiomysql", "PyMySQL", "SQLAlchemy", "alembic"])
def test_database_drivers_are_pinned(pkg):
    assert re.search(rf"^{pkg}==\S+", (ROOT / "constraints.txt").read_text(encoding="utf-8"), re.M | re.I)


def test_default_make_targets_do_not_start_postgres():
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    up = re.search(r"^up:.*?(?=^\S)", mk, re.M | re.S).group(0)
    assert "$(COMPOSE) up -d --build --wait mysql" in up and "postgres" not in up
    assert re.search(r"^COMPOSE := .*docker-compose\.mysql\.yml", mk, re.M)


def _evals(root: Path):
    spec = importlib.util.spec_from_file_location("evals_run_under_test", ROOT / "evals" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve their module while it loads
    spec.loader.exec_module(mod)
    mod.ROOT = root
    return mod


def test_eval_invariants_pass_on_the_mysql_schema():
    ok, detail = _evals(ROOT).invariant_schema()
    assert ok, detail


@pytest.mark.parametrize(
    "needle", ["CREATE TRIGGER trg_audit_no_delete", "CHECK (label_source = 'realised')", "basis_refs JSON NOT NULL"]
)
def test_eval_invariants_fail_when_a_mysql_constraint_is_removed(tmp_path, needle):
    (tmp_path / "migrations_mysql/baseline").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    shutil.copy(BASELINE, tmp_path / "migrations_mysql/baseline/m0001_schema.sql")
    current = (ROOT / "scripts/schema_mysql.sql").read_text(encoding="utf-8")
    assert needle in current
    (tmp_path / "scripts/schema_mysql.sql").write_text(current.replace(needle, "-- removed"), encoding="utf-8")
    ok, detail = _evals(tmp_path).invariant_schema()
    assert not ok and "schema_mysql.sql" in detail


def test_engine_sets_the_session_zone_on_every_connection(monkeypatch):
    seen = {}

    def fake(url, **kw):
        seen.update(kw)
        raise SystemExit

    monkeypatch.setattr(session_mod, "create_async_engine", fake)
    with pytest.raises(SystemExit):
        session_mod.create_engine_from_url("mysql+asyncmy://u@h/d")
    assert seen["connect_args"]["init_command"] == "SET time_zone = '+00:00'"


async def test_session_zone_is_utc_on_a_real_connection():
    engine = session_mod.create_engine_from_url(session_mod.get_mysql_test_url(), pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as c:
            assert (await c.execute(text("SELECT @@session.time_zone"))).scalar() == "+00:00"
        await db_pkg.verify_mysql_session(engine)
    finally:
        await engine.dispose()


async def test_verify_refuses_a_non_utc_session(monkeypatch):
    engine = session_mod.create_engine_from_url(session_mod.get_mysql_test_url(), pool_size=1, max_overflow=0)

    class R:
        def scalar(self):
            return "+05:30"

    class C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, _q):
            return R()

    class E:
        dialect = engine.dialect

        def connect(self):
            return C()

    try:
        with pytest.raises(RuntimeError, match="UTC"):
            await session_mod.verify_mysql_session(E())
    finally:
        await engine.dispose()


async def test_raw_cypher_is_an_explicit_error_and_is_audited(monkeypatch):
    calls = []

    async def allow(*a, **k):
        return None

    async def rec(_s, _p, action, target, meta):
        calls.append(action)

    class Ctx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(graph_router, "check_access", allow)
    monkeypatch.setattr(graph_router.audit_service, "record", rec)
    monkeypatch.setattr(graph_router, "session_scope", Ctx)
    with pytest.raises(Problem) as e:
        await graph_router.query(
            template="cypher", id=None, label=None, depth=1, limit=10, cypher="MATCH (n) RETURN n", p=None, session=None
        )
    assert e.value.status == 410
    assert calls == ["graph.cypher.rejected"]
