"""Migration/backup connection security: secrets never from argv, verified TLS for remote hosts.

The handshake tests run a real TLS server on loopback with a throwaway CA, so certificate and hostname
verification are exercised end to end rather than asserted from context flags alone.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import socket
import ssl
import threading
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from scripts import migrate_pg_to_mysql as etl
from scripts import secure_connect as sc

# ---------------------------------------------------------------- secrets


def test_read_secret_prefers_value_then_file(tmp_path: Path):
    f = tmp_path / "pw"
    f.write_text("from-file\n", encoding="utf-8")
    assert sc.read_secret(("A", "B"), {"B": "b-val", "A_FILE": str(f)}) == "from-file"
    assert sc.read_secret(("A", "B"), {"A": "a-val", "A_FILE": str(f)}) == "a-val"
    assert sc.read_secret(("A",), {}) is None


def test_dev_default_password_only_for_loopback():
    assert sc.resolve_password(("X",), "127.0.0.1", local_default="dev", env={}) == "dev"
    with pytest.raises(ValueError, match=r"no password for db\.example\.com"):
        sc.resolve_password(("X",), "db.example.com", local_default="dev", env={})


def test_password_file_must_not_be_empty(tmp_path: Path):
    f = tmp_path / "empty"
    f.write_text("  \n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        sc.resolve_password(("X",), "127.0.0.1", password_file=str(f), env={})


@pytest.mark.parametrize("flag", ["--pg-password", "--mysql-password"])
def test_etl_rejects_password_on_command_line(flag, capsys):
    with pytest.raises(SystemExit) as ei:
        etl.build_parser({}).parse_args([flag, "s3cret"])
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert "not accepted" in err and "s3cret" not in err


# ---------------------------------------------------------------- TLS policy


def test_loopback_defaults_to_plaintext_and_remote_to_verify_identity():
    assert sc.mysql_ssl_context("127.0.0.1", env={}) is None
    ctx = sc.mysql_ssl_context("db.example.com", env={})
    assert ctx is not None and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2
    assert sc.pg_ssl_options("127.0.0.1", env={}) == {}
    assert sc.pg_ssl_options("db.example.com", env={}) == {"sslmode": "verify-full"}


@pytest.mark.parametrize("mode", ["DISABLED", "REQUIRED"])
def test_unverified_mysql_tls_to_remote_host_is_refused(mode):
    with pytest.raises(sc.InsecureConnectionError):
        sc.mysql_ssl_context("db.example.com", mode, env={})
    ctx = sc.mysql_ssl_context("db.example.com", mode, env={sc.ALLOW_UNVERIFIED_ENV: "1"})
    assert (ctx is None) if mode == "DISABLED" else (ctx.verify_mode == ssl.CERT_NONE)


@pytest.mark.parametrize("mode", ["disable", "prefer", "require"])
def test_unverified_pg_tls_to_remote_host_is_refused(mode):
    with pytest.raises(sc.InsecureConnectionError):
        sc.pg_ssl_options("pg.example.com", mode, env={})


def test_verify_ca_checks_chain_but_not_hostname():
    ctx = sc.mysql_ssl_context("10.0.0.5", "VERIFY_CA", env={})
    assert ctx.verify_mode == ssl.CERT_REQUIRED and not ctx.check_hostname


def test_etl_configs_remote_require_secret_and_carry_verified_tls():
    args = etl.build_parser({}).parse_args(
        ["--pg-host", "pg.internal", "--pg-sslrootcert", "system", "--mysql-host", "mysql.internal"]
    )
    with pytest.raises(ValueError, match=r"no password for pg\.internal"):
        etl.build_connection_configs(args, env={})
    env = {"MIGRATION_PG_PASSWORD": "p", "MIGRATION_MYSQL_PASSWORD": "m"}
    pg, my = etl.build_connection_configs(args, env=env)
    assert pg["sslmode"] == "verify-full" and pg["sslrootcert"] == "system" and pg["password"] == "p"
    assert isinstance(my["ssl"], ssl.SSLContext) and my["ssl"].check_hostname and my["password"] == "m"
    assert sc.describe_tls(my) == "TLS (verify identity)"


def test_etl_configs_loopback_unchanged_for_local_rehearsal():
    # neither side has a committed loopback default any more
    env = {"MIGRATION_MYSQL_PASSWORD": "from-env", "MIGRATION_PG_PASSWORD": "pg-from-env"}
    args = etl.build_parser(env).parse_args([])
    pg, my = etl.build_connection_configs(args, env=env)
    assert "sslmode" not in pg and "ssl" not in my
    assert (pg["host"], pg["port"], my["host"], my["port"]) == ("127.0.0.1", 55432, "127.0.0.1", 53306)
    assert my["password"] == "from-env" and pg["password"] == "pg-from-env"


def test_etl_refuses_mysql_target_without_a_configured_password_even_on_loopback():
    args = etl.build_parser({}).parse_args([])
    with pytest.raises(ValueError, match=r"no password for 127\.0\.0\.1"):
        etl.build_connection_configs(args, env={"MIGRATION_PG_PASSWORD": "pg-from-env"})


def test_etl_refuses_postgres_source_without_a_configured_password_even_on_loopback():
    args = etl.build_parser({}).parse_args([])
    with pytest.raises(ValueError, match=r"no password for 127\.0\.0\.1"):
        etl.build_connection_configs(args, env={"MIGRATION_MYSQL_PASSWORD": "from-env"})


# ---------------------------------------------------------------- real handshakes


def _cert(subject_cn: str, issuer_key, issuer_name, key, *, ca: bool, san: list[x509.GeneralName] | None = None):
    now = dt.datetime.now(dt.UTC)
    b = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_cn)]))
        .issuer_name(issuer_name or x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_cn)]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if san:
        b = b.add_extension(x509.SubjectAlternativeName(san), critical=False)
    if ca:
        b = b.add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True
        ).add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
    else:
        b = b.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False
        ).add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    return b.sign(issuer_key, hashes.SHA256())


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    d = tmp_path_factory.mktemp("pki")
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = _cert("Cortex Test CA", ca_key, None, ca_key, ca=True)
    srv_key = ec.generate_private_key(ec.SECP256R1())
    srv = _cert(
        "localhost",
        ca_key,
        ca.subject,
        srv_key,
        ca=False,
        san=[x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))],
    )
    other_key = ec.generate_private_key(ec.SECP256R1())
    other_ca = _cert("Unrelated CA", other_key, None, other_key, ca=True)
    pem = serialization.Encoding.PEM
    (d / "ca.pem").write_bytes(ca.public_bytes(pem))
    (d / "other-ca.pem").write_bytes(other_ca.public_bytes(pem))
    (d / "server.pem").write_bytes(srv.public_bytes(pem))
    (d / "server.key").write_bytes(
        srv_key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return d


@pytest.fixture(scope="module")
def tls_server(pki):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(pki / "server.pem", pki / "server.key")
    lsock = socket.create_server(("127.0.0.1", 0))
    port = lsock.getsockname()[1]
    stop = threading.Event()

    def serve():
        lsock.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = lsock.accept()
            except TimeoutError:
                continue
            try:
                with ctx.wrap_socket(conn, server_side=True) as s:
                    s.sendall(b"ok")
            except (ssl.SSLError, OSError):
                pass

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    yield port
    stop.set()
    t.join(2)
    lsock.close()


def _handshake(ctx: ssl.SSLContext, port: int, server_hostname: str) -> bytes:
    with (
        socket.create_connection(("127.0.0.1", port), timeout=5) as raw,
        ctx.wrap_socket(raw, server_hostname=server_hostname) as s,
    ):
        return s.recv(2)


def test_verify_identity_accepts_matching_ca_and_hostname(pki, tls_server):
    ctx = sc.mysql_ssl_context("localhost", "VERIFY_IDENTITY", ca=str(pki / "ca.pem"), env={})
    assert _handshake(ctx, tls_server, "localhost") == b"ok"


def test_verify_identity_rejects_wrong_hostname(pki, tls_server):
    ctx = sc.mysql_ssl_context("db.example.com", "VERIFY_IDENTITY", ca=str(pki / "ca.pem"), env={})
    with pytest.raises(ssl.SSLCertVerificationError, match=r"match|mismatch"):
        _handshake(ctx, tls_server, "db.example.com")


def test_verify_ca_rejects_untrusted_issuer(pki, tls_server):
    ctx = sc.mysql_ssl_context("db.example.com", "VERIFY_CA", ca=str(pki / "other-ca.pem"), env={})
    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(ctx, tls_server, "db.example.com")


def test_verify_ca_accepts_trusted_issuer_under_another_name(pki, tls_server):
    ctx = sc.mysql_ssl_context("db.example.com", "VERIFY_CA", ca=str(pki / "ca.pem"), env={})
    assert _handshake(ctx, tls_server, "db.example.com") == b"ok"
