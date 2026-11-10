"""MySQL schema application and versioning (no database required).

- schema_mysql.sql uses DELIMITER $$ for triggers; the old split(";") in tests/integration/conftest.py tore
  trigger bodies apart, so a fresh test database never got the I3 / append-only audit triggers.
- migrations/ is PostgreSQL-only; the MySQL compose stack ran it and failed on CREATE EXTENSION. MySQL now
  has its own history in migrations_mysql/ (alembic -n mysql).
"""

from __future__ import annotations

import configparser
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from platform_core.db.mysql_schema import schema_statements, split_mysql_script

ROOT = Path(__file__).resolve().parents[2]


def test_split_honours_delimiter_and_drops_comments():
    sql = (
        "-- header\nSET NAMES utf8mb4;\nCREATE TABLE t (\n  id INT -- inline note stays\n);\n"
        "DELIMITER $$\nCREATE TRIGGER x BEFORE UPDATE ON t FOR EACH ROW\nBEGIN\n"
        "  SET NEW.id = 1;\n  SET NEW.id = 2;\nEND$$\nDELIMITER ;\nINSERT INTO t VALUES (1);\n"
    )
    stmts = split_mysql_script(sql)
    assert len(stmts) == 4
    assert stmts[2].startswith("CREATE TRIGGER") and stmts[2].endswith("END")
    assert "SET NEW.id = 1;\n  SET NEW.id = 2;" in stmts[2]
    assert stmts[3] == "INSERT INTO t VALUES (1)"


def test_split_rejects_unterminated_statement():
    with pytest.raises(ValueError, match="unterminated"):
        split_mysql_script("CREATE TABLE t (id INT)")


def test_real_schema_yields_tables_triggers_and_no_admin_statements():
    stmts = schema_statements()
    kinds = [" ".join(s.split()[:2]).upper() for s in stmts]
    assert kinds.count("CREATE TABLE") == 49
    assert kinds.count("CREATE TRIGGER") == 4
    assert not any(s.upper().startswith(("CREATE DATABASE", "GRANT ")) for s in stmts)
    assert all("SIGNAL SQLSTATE" in s for s in stmts if s.startswith("CREATE TRIGGER trg_audit"))
    admin = schema_statements(include_admin=True)
    assert len(admin) == len(stmts) + 2


def _load_baseline():
    path = ROOT / "migrations_mysql" / "versions" / "m0001_mysql_baseline.py"
    spec = importlib.util.spec_from_file_location("m0001_mysql_baseline", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_baseline_revision_applies_every_schema_statement_without_interpolation():
    mod = _load_baseline()
    assert mod.revision == "m0001_mysql_baseline" and mod.down_revision is None
    bind = MagicMock()
    with patch.object(mod.op, "get_bind", return_value=bind, create=True):
        mod.upgrade()
    executed = [c.args[0] for c in bind.exec_driver_sql.call_args_list]
    assert executed == schema_statements()
    assert all(c.kwargs["execution_options"] == {"no_parameters": True} for c in bind.exec_driver_sql.call_args_list)


def test_alembic_has_separate_mysql_section():
    ini = configparser.ConfigParser()
    ini.read(ROOT / "alembic.ini")
    assert ini["alembic"]["script_location"] == "migrations_mysql"  # MySQL is the default history
    assert ini["postgres"]["script_location"] == "migrations"  # rollback window only
    assert ini["mysql"]["script_location"] == "migrations_mysql"


def test_container_shell_scripts_are_lf_and_pinned_by_gitattributes():
    """Scripts executed by Linux containers break on CRLF; core.autocrlf=true would write CRLF on checkout."""
    scripts = [*(ROOT / "infra").rglob("*.sh"), *(ROOT / "apps" / "web" / "nginx").glob("*.envsh")]
    assert len(scripts) >= 4
    with_cr = [str(p.relative_to(ROOT)) for p in scripts if b"\r" in p.read_bytes()]
    assert with_cr == []
    rules = (ROOT / ".gitattributes").read_text(encoding="utf-8").split()
    for pattern in ("*.sh", "*.envsh"):
        i = rules.index(pattern)
        assert rules[i + 1 : i + 3] == ["text", "eol=lf"]


class _ComposeLoader(yaml.SafeLoader):
    """SafeLoader that accepts Compose's merge tags (!override / !reset)."""


for _tag in ("!override", "!reset"):
    _ComposeLoader.add_constructor(
        _tag,
        lambda loader, node: (
            loader.construct_mapping(node)
            if isinstance(node, yaml.MappingNode)
            else loader.construct_sequence(node)
            if isinstance(node, yaml.SequenceNode)
            else loader.construct_scalar(node)
        ),
    )


def test_mysql_compose_runs_mysql_history_and_provisions_keycloak_db():
    compose = yaml.load(
        (ROOT / "infra" / "docker-compose.mysql.yml").read_text(encoding="utf-8"), Loader=_ComposeLoader
    )
    assert compose["services"]["migrate"]["command"] == ["alembic", "-n", "mysql", "upgrade", "head"]
    # The base file makes these wait for a healthy postgres, which is a disabled stub in MySQL mode.
    for svc in ("migrate", "keycloak"):
        assert set(compose["services"][svc]["depends_on"]) == {"mysql"}
    # Binary logging is on, so the app user can only create the schema's triggers with this flag (error 1419).
    mysql_cmd = compose["services"]["mysql"]["command"]
    assert "--log-bin=mysql-bin" in mysql_cmd and "--log-bin-trust-function-creators=1" in mysql_cmd
    text = (ROOT / "infra" / "docker-compose.mysql.yml").read_text(encoding="utf-8")
    assert text.count("depends_on: !override") == 2
    assert "./mysql/init:/docker-entrypoint-initdb.d:ro" in compose["services"]["mysql"]["volumes"]
    init = (ROOT / "infra" / "mysql" / "init" / "01-keycloak.sh").read_bytes()
    assert b"CREATE DATABASE IF NOT EXISTS keycloak" in init
    assert b"\r" not in init  # bytes: read_text() would silently translate CRLF and hide it
    dockerfile = (ROOT / "infra" / "api" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY migrations_mysql ./migrations_mysql" in dockerfile
    assert "COPY scripts/schema_mysql.sql ./scripts/schema_mysql.sql" in dockerfile


def _load_revision(name: str):
    path = ROOT / "migrations_mysql" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("present", [False, True])
def test_m0003_adds_opportunity_list_indexes_online_and_is_idempotent(present):
    mod = _load_revision("m0003_opportunity_list_indexes")
    assert (mod.revision, mod.down_revision) == ("m0003_opportunity_list_indexes", "m0002_legal_hold_columns")
    bind = MagicMock()
    bind.execute.return_value.scalar.return_value = 1 if present else 0
    with patch.object(mod.op, "get_bind", return_value=bind, create=True):
        mod.upgrade()
    ddl = [c.args[0] for c in bind.exec_driver_sql.call_args_list]
    if present:
        assert ddl == []
        return
    assert len(ddl) == 3 and all(d.endswith("ALGORITHM=INPLACE, LOCK=NONE") for d in ddl)
    schema = (ROOT / "scripts" / "schema_mysql.sql").read_text(encoding="utf-8")
    for name, cols in mod.INDEXES.items():  # fresh installs get the same indexes
        assert f"INDEX {name} {cols}," in schema
