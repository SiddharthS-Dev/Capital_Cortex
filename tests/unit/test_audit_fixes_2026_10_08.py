"""Regressions for the 2026-10-08 audit (governance): content flags that could be dodged, and the sentence split
that feeds a human edit through the citation checker."""

from __future__ import annotations

from cortex.l7_governance.policy_engine import content_flags
from cortex.l8_actuation.api.routers.agents import _sentences


def test_portal_name_does_not_erase_financial_terms_from_the_body() -> None:
    # the portal (recipient) used to be deleted from the whole serialised payload before scanning
    f = content_flags({"portal": "term sheet", "body": "Attached: the term sheet for review."}, "export", "term sheet")
    assert f["contains_financial_terms"]


def test_financial_terms_survive_hyphens_joins_and_odd_spaces() -> None:
    for body in ("the term-sheet", "our termsheet", "the term sheet", "a pre money round", "valuation‑cap"):
        assert content_flags({"body": body}, "outbound")["contains_financial_terms"], body
    assert not content_flags({"body": "Thanks for the call today."}, "outbound")["contains_financial_terms"]


def test_recipient_address_ignored_for_pii_only() -> None:
    to = "board@inspironics.net"
    assert not content_flags({"to": to, "body": f"Dear {to}, see attached."}, "outbound", to)["contains_pii"]
    assert content_flags({"to": to, "body": "Call jane.doe@example.com"}, "outbound", to)["contains_pii"]
    # a webhook URL is an address field, never scanned, but the body still is
    f = content_flags(
        {"url": "https://hooks.example.com/valuation", "body": "status ping"},
        "outbound",
        "https://hooks.example.com/valuation",
    )
    assert not f["contains_financial_terms"]


def test_edited_text_is_checked_in_full() -> None:
    long = ("word " * 600).strip() + ". Valuation cap $40M agreed."
    pieces = _sentences(long)
    assert all(len(x) <= 1900 for x in pieces)
    assert pieces[-1] == "Valuation cap $40M agreed."
    assert " ".join(pieces).split() == long.split()


def test_prod_profile_refuses_dev_secrets_and_dev_identity() -> None:
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("check_env", Path("scripts/check_env.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    compose = Path("infra/docker-compose.yml").read_text(encoding="utf-8")
    assert mod.problems({}, "dev", compose) == [], "a laptop needs no configuration"
    dev_env = dict(mod.DEV_DEFAULTS)
    found = mod.problems(dev_env, "prod", compose)
    assert any("POSTGRES_PASSWORD is still the development default" in p for p in found)
    assert any("APPROVAL_SIGNING_KEY" in p for p in found)
    assert any("start-dev" in p for p in found) and any("Vault runs in dev mode" in p for p in found)
    strong = {k: f"{k.lower()}-a-real-secret-0123456789" for k in mod.DEV_DEFAULTS} | {"APPROVAL_SIGNING_KEY": "k" * 40}
    prod_compose = compose.replace('"start-dev"', '"start"').replace("VAULT_DEV_ROOT_TOKEN_ID", "VAULT_ADDR")
    assert mod.problems(strong, "prod", prod_compose) == []


def test_unauthenticated_services_bind_to_loopback() -> None:
    from pathlib import Path

    import yaml

    services = yaml.safe_load(Path("infra/docker-compose.yml").read_text(encoding="utf-8"))["services"]
    for name in ("postgres", "redis", "minio", "opa", "vault", "prometheus", "mailpit"):
        for port in services[name].get("ports", []):
            assert port.startswith("${INTERNAL_BIND_ADDR:-127.0.0.1}:"), (name, port)


async def test_dlq_replay_passes_the_workers_job_token_check(verifier, make_token) -> None:
    import time

    import fakeredis.aioredis

    from platform_core.bus import Envelope
    from platform_core.bus.streams import Bus

    bus = Bus(fakeredis.aioredis.FakeRedis())
    old = Envelope(type="ingest.run", payload={"source_id": "s1"}, actor_token="expired-original")
    old.ts = time.time() - 2 * 3600  # dead-lettered two hours ago
    await bus.dead_letter("system.jobs", "g", "1-0", old, RuntimeError("upstream timeout"))
    [dl] = await bus.dlq_list("system.jobs")
    fresh = make_token(["admin"])  # the replayer's token, issued now
    await bus.dlq_replay("system.jobs", dl["dlq_id"], actor_token=fresh)
    [(_, fields)] = await bus.r.xrange("system.jobs")
    env = Envelope.from_fields({k.decode(): v.decode() for k, v in fields.items()})
    # the worker judges the token as of the job's publish time: the replay must be its own publish
    assert verifier.verify_job_sync(env.actor_token, published_at=env.ts).roles == frozenset({"admin"})


async def test_long_job_is_not_reclaimed_and_rerun_by_another_consumer() -> None:
    import asyncio

    import fakeredis.aioredis

    from platform_core.bus import Envelope
    from platform_core.bus.streams import Bus

    bus = Bus(fakeredis.aioredis.FakeRedis())
    await bus.ensure_group("jobs", "g")
    await bus.publish("jobs", Envelope(type="ingest.run", payload={}))
    runs: list[str] = []

    async def slow(env: Envelope) -> None:
        runs.append(env.id)
        await asyncio.sleep(0.6)  # ten times the reclaim window below

    first = asyncio.create_task(bus.consume_once("jobs", "g", "c1", slow, block_ms=10, min_idle_ms=60))
    await asyncio.sleep(0.05)
    for _ in range(8):  # a second consumer keeps trying to reclaim while c1 is still working
        await bus.consume_once("jobs", "g", "c2", slow, block_ms=10, min_idle_ms=60)
        await asyncio.sleep(0.05)
    await first
    assert len(runs) == 1, "the job ran once"
    assert not await bus.r.xpending_range("jobs", "g", min="-", max="+", count=10), "and was acked"


def test_date_only_deadline_closes_at_end_of_day_in_the_source_zone() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from cortex.l1_perception.mapping import to_date
    from cortex.l1_perception.models import RawItem
    from cortex.l1_perception.normalizer import normalize
    from cortex.l1_perception.registry import load_configs

    ny = ZoneInfo("America/New_York")
    assert to_date("10/15/2026", tz="America/New_York", end_of_day=True) == datetime(
        2026, 10, 15, 23, 59, 59, tzinfo=ny
    )
    # an explicit time or zone is kept as given
    assert to_date("10/15/2026 5:00 PM", tz="America/New_York", end_of_day=True) == datetime(
        2026, 10, 15, 17, tzinfo=ny
    )
    assert to_date("2026-10-15T00:00:00Z", tz="America/New_York", end_of_day=True).utcoffset().total_seconds() == 0
    assert to_date("2026-10-15 12:34:56", end_of_day=True).hour == 12, "a real time is never taken for 'no time'"
    # the Grants.gov source is configured for US Eastern: the deadline is not shifted to the evening before
    cfg = load_configs()["grants_gov"]
    payload = {"id": "1", "title": "T", "synopsis": {"responseDate": "10/15/2026"}}
    sig = normalize(cfg, RawItem(payload=payload, url="https://example.org", fetched_at=datetime.now(ny)))
    assert sig.deadline == datetime(2026, 10, 15, 23, 59, 59, tzinfo=ny)
