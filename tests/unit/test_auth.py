import time

import jwt
import pytest

from platform_core.auth.abac import Resource, classification_allowed
from platform_core.auth.mfa import enforce_role_mfa, enforce_step_up
from platform_core.auth.rbac import get_rbac
from platform_core.errors import Forbidden, StepUpRequired, Unauthorized


def test_verify_valid_token(verifier, make_token):
    p = verifier.verify_sync(make_token(["analyst"], username="ana"))
    assert p.roles == frozenset({"analyst"})  # non-Cortex realm roles are filtered out
    assert p.username == "ana" and p.mfa


def test_wrong_issuer_rejected(verifier, make_token):
    with pytest.raises(Unauthorized):
        verifier.verify_sync(make_token(["analyst"], iss="https://evil.example/realms/cortex"))


def test_wrong_audience_rejected(verifier, make_token):
    with pytest.raises(Unauthorized):
        verifier.verify_sync(make_token(["analyst"], aud="some-other-api"))


def test_expired_rejected(verifier, make_token):
    with pytest.raises(Unauthorized):
        verifier.verify_sync(make_token(["analyst"], ttl=-120))


def test_forged_signature_rejected(verifier):
    from cryptography.hazmat.primitives.asymmetric import rsa

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    tok = jwt.encode(
        {"iss": verifier.settings.oidc_issuer, "aud": "cortex-api", "sub": "x", "iat": now, "exp": now + 60},
        other,
        algorithm="RS256",
    )
    with pytest.raises(Unauthorized):
        verifier.verify_sync(tok)


def test_hs256_alg_confusion_rejected(verifier):
    now = int(time.time())
    tok = jwt.encode(
        {"iss": verifier.settings.oidc_issuer, "aud": "cortex-api", "sub": "x", "iat": now, "exp": now + 60},
        "secret",
        algorithm="HS256",
    )
    with pytest.raises(Unauthorized):
        verifier.verify_sync(tok)


@pytest.mark.parametrize(
    "role,perm,expected",
    [
        ("analyst", "opportunity:read", True),
        ("analyst", "audit:read", False),
        ("analyst", "approval:decide", False),
        ("approver", "approval:decide", True),
        ("approver", "opportunity:write", False),
        ("auditor", "audit:verify", True),
        ("auditor", "outbox:send", False),
        ("executive", "board_report:read", True),
        ("executive", "agent:run", False),
        ("admin", "anything:whatsoever", True),
    ],
)
def test_rbac_matrix(verifier, make_token, role, perm, expected):
    p = verifier.verify_sync(make_token([role]))
    assert get_rbac().allows(p, perm) is expected


def test_service_client_scoping(verifier, make_token):
    ingest = verifier.verify_sync(
        make_token(["service"], azp="cortex-ingestion", mfa=False, username="service-account-cortex-ingestion")
    )
    assert ingest.is_service
    assert get_rbac().allows(ingest, "signal:write")
    assert not get_rbac().allows(ingest, "graph:write")  # role has it, client scope does not
    rogue = verifier.verify_sync(make_token(["service"], azp="rogue", mfa=False))
    assert not get_rbac().allows(rogue, "system:ping")


@pytest.mark.parametrize("role", ["admin", "approver", "auditor"])
def test_mfa_required_roles(verifier, make_token, role):
    with pytest.raises(Forbidden):
        enforce_role_mfa(verifier.verify_sync(make_token([role], mfa=False)), get_rbac())
    enforce_role_mfa(verifier.verify_sync(make_token([role], mfa=True)), get_rbac())


def test_mfa_optional_for_analyst(verifier, make_token):
    enforce_role_mfa(verifier.verify_sync(make_token(["analyst"], mfa=False)), get_rbac())


def test_mfa_via_acr(verifier, make_token):
    p = verifier.verify_sync(make_token(["approver"], mfa=False, acr="mfa"))
    assert p.mfa


def test_step_up(verifier, make_token):
    enforce_step_up(verifier.verify_sync(make_token(["approver"], auth_age=30)), 300)
    with pytest.raises(StepUpRequired):
        enforce_step_up(verifier.verify_sync(make_token(["approver"], auth_age=900)), 300)
    with pytest.raises(StepUpRequired):
        enforce_step_up(verifier.verify_sync(make_token(["analyst"], mfa=False)), 300)


def test_step_up_without_mfa_when_switched_off(verifier, make_token):
    enforce_step_up(verifier.verify_sync(make_token(["approver"], mfa=False, auth_age=30)), 300, require_mfa=False)
    with pytest.raises(StepUpRequired):  # recency is still required
        enforce_step_up(verifier.verify_sync(make_token(["approver"], mfa=False, auth_age=900)), 300, require_mfa=False)


def test_classification_clearance(verifier, make_token):
    analyst = verifier.verify_sync(make_token(["analyst"]))
    auditor = verifier.verify_sync(make_token(["auditor"]))
    restricted = Resource("document", classification="restricted")
    assert not classification_allowed(analyst, restricted, get_rbac())
    assert classification_allowed(auditor, restricted, get_rbac())
    assert classification_allowed(analyst, Resource("document", classification="confidential"), get_rbac())
