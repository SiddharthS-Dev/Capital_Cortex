"""Regression tests for the 2026-10-03 security review (approval flags, grant submissions, DLQ replay, data room)."""

import fakeredis.aioredis

from cortex.l7_governance.policy_engine import content_flags, effective_flags, is_grant_class, required_approvals
from cortex.l8_actuation.dataroom import package_readable
from platform_core.auth.principal import Principal
from platform_core.bus.streams import Bus, Envelope


def test_stale_stored_flags_cannot_hide_financial_or_pii_content():
    payload = {"recommendation": "Accept the term sheet at a $12M valuation; contact jane.doe@example.org"}
    stale = {"contains_financial_terms": False, "contains_pii": False, "is_grant_submission": False}
    flags = effective_flags(stale, payload, "export")
    assert flags["contains_financial_terms"] and flags["contains_pii"]
    assert required_approvals(flags) == 2


def test_stored_flags_are_kept_when_content_no_longer_shows_them():
    assert effective_flags({"is_grant_submission": True}, {"title": "x"}, "export")["is_grant_submission"]


def test_grant_type_proposals_are_submissions():
    assert is_grant_class("grant") and is_grant_class("government_program")
    assert not is_grant_class("venture_equity") and not is_grant_class(None)
    assert content_flags({"title": "x"}, "submission")["is_grant_submission"]


async def test_dlq_replay_runs_as_the_replayer_not_the_original_actor():
    bus = Bus(fakeredis.aioredis.FakeRedis())
    env = Envelope(type="outbox.release", payload={"outbox_id": "o1"}, actor_token="approver-token")
    await bus.dead_letter("system.jobs", "g", "1-0", env, RuntimeError("Unauthorized: expired"))
    [dl] = await bus.dlq_list("system.jobs")
    await bus.dlq_replay("system.jobs", dl["dlq_id"], actor_token="analyst-token")
    [(_, fields)] = await bus.r.xrange("system.jobs")
    assert Envelope.from_fields({k.decode(): v.decode() for k, v in fields.items()}).actor_token == "analyst-token"


def _user(roles: list[str]) -> Principal:
    return Principal(sub="u", username="u", roles=frozenset(roles), token="t")


def test_package_with_a_restricted_file_is_not_readable_below_restricted_clearance():
    manifest = {"files": [{"classification": "internal"}, {"classification": "restricted"}]}
    assert not package_readable(_user(["analyst"]), manifest)
    assert package_readable(_user(["admin"]), manifest)
