"""Queued jobs: tokens judged at publish time; JWKS outages retry; poison messages never crash the consumer."""

import time

import fakeredis.aioredis
import jwt
import pytest

from platform_core.auth.oidc import MAX_JOB_QUEUE_SECONDS, TokenVerifier
from platform_core.bus.streams import Bus
from platform_core.config import get_settings
from platform_core.errors import ServiceUnavailable, Unauthorized


def test_job_runs_when_token_expired_after_publishing(verifier, make_token):
    now = time.time()
    tok = make_token(["analyst"], ttl=900)
    p = verifier.verify_job_sync(tok, published_at=now, now=now + 3600)  # waited an hour in the queue
    assert p.roles == frozenset({"analyst"})


def test_job_rejected_when_token_already_expired_at_publish(verifier, make_token):
    now = time.time()
    with pytest.raises(Unauthorized):
        verifier.verify_job_sync(make_token(["analyst"], ttl=-120), published_at=now, now=now)


def test_job_rejected_after_max_queue_age(verifier, make_token):
    now = time.time()
    with pytest.raises(Unauthorized):
        verifier.verify_job_sync(make_token(["analyst"]), published_at=now, now=now + MAX_JOB_QUEUE_SECONDS + 60)


def test_job_token_signature_still_verified(verifier):
    from cryptography.hazmat.primitives.asymmetric import rsa

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    forged = jwt.encode({"iss": get_settings().oidc_issuer, "aud": "cortex-api", "sub": "x", "iat": now, "exp": now + 60},
                        other, algorithm="RS256", headers={"kid": "test"})  # fmt: skip
    with pytest.raises(Unauthorized):
        verifier.verify_job_sync(forged, published_at=now, now=now)


def test_jwks_outage_is_temporary_not_unauthorized(make_token):
    class DownJWKS:
        def get_signing_key_from_jwt(self, token):
            raise jwt.PyJWKClientError("connection refused")

    v = TokenVerifier(get_settings(), DownJWKS())
    with pytest.raises(ServiceUnavailable) as e:
        v.verify_sync(make_token(["analyst"]))
    assert not e.value.permanent  # the bus retries instead of dead-lettering


async def test_malformed_message_is_dead_lettered_not_raised():
    bus = Bus(fakeredis.aioredis.FakeRedis())
    await bus.ensure_group("system.jobs", "g")
    await bus.r.xadd("system.jobs", {"payload": "{not json"})  # no type, bad JSON

    async def handler(env):
        raise AssertionError("must not be called")

    await bus.consume_once("system.jobs", "g", "c1", handler, block_ms=10)
    assert await bus.r.xlen("system.jobs.dlq") == 1


def test_signal_processing_accepts_the_ingestion_permission():
    from cortex.worker import JOBS

    assert "source:run" in JOBS["signal.ingested"].permission
