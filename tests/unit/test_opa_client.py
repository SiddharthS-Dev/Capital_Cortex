import httpx
import respx

from platform_core.policy.opa import OPAClient

URL = "http://opa.test"


@respx.mock
async def test_allow():
    respx.post(f"{URL}/v1/data/cortex/authz").respond(json={"result": {"allow": True, "deny": []}})
    d = await OPAClient(URL).evaluate("cortex.authz", {"x": 1})
    assert d.allow and d.reasons == []


@respx.mock
async def test_deny_reasons():
    respx.post(f"{URL}/v1/data/cortex/authz").respond(
        json={"result": {"allow": False, "deny": ["mfa_required", "classification_exceeds_clearance"]}}
    )
    d = await OPAClient(URL).evaluate("cortex.authz", {})
    assert not d.allow and d.reasons == ["classification_exceeds_clearance", "mfa_required"]


@respx.mock
async def test_fail_closed_on_error():
    respx.post(f"{URL}/v1/data/cortex/authz").mock(side_effect=httpx.ConnectError("down"))
    d = await OPAClient(URL).evaluate("cortex.authz", {})
    assert not d.allow and "unavailable" in d.reasons[0]


@respx.mock
async def test_fail_closed_on_500():
    respx.post(f"{URL}/v1/data/cortex/authz").respond(500)
    assert not (await OPAClient(URL).evaluate("cortex.authz", {})).allow


@respx.mock
async def test_fail_closed_on_undefined():
    respx.post(f"{URL}/v1/data/cortex/authz").respond(json={})
    d = await OPAClient(URL).evaluate("cortex.authz", {})
    assert not d.allow and d.reasons == ["policy undefined"]


@respx.mock
async def test_non_bool_allow_is_deny():
    respx.post(f"{URL}/v1/data/cortex/authz").respond(json={"result": {"allow": "yes"}})
    assert not (await OPAClient(URL).evaluate("cortex.authz", {})).allow
