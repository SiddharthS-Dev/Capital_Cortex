"""The outreach workbook's 10_Outreach_Tracker sheet: its status details reach the signal by Prospect ID."""

import io
from datetime import date, datetime

from openpyxl import Workbook

from cortex.l1_perception.adapters.base import FetchContext, get_adapter
from cortex.l1_perception.normalizer import normalize
from cortex.l1_perception.registry import load_configs
from cortex.l2_representation.outreach_writer import tracker_values

IMPORT_HEADER = [
    "prospect_id",
    "engine",
    "module",
    "organization",
    "route",
    "engagement_outlook",
    "status",
    "proposed_owner",
]
TRACKER_HEADER = ["Prospect ID", "Organization", "Status", "First sent", "Next action date", "Confirmed contact / reply",
                  "Eligibility decision", "Notes / outcome"]  # fmt: skip


def _workbook(tracker: bool = True) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "12_Meris_Import"
    ws.append(IMPORT_HEADER)
    ws.append(
        [
            "CC-001",
            "Meris",
            "Capital Cortex",
            "AWS Activate",
            "Contact now",
            "High",
            "Not contacted",
            "Senthil (proposed)",
        ]
    )
    ws.append(
        ["CC-002", "Meris", "Capital Cortex", "Rutgers", "Contact now", "Medium", "Not contacted", "Kumar (proposed)"]
    )
    if tracker:
        t = wb.create_sheet("10_Outreach_Tracker")
        t.append(TRACKER_HEADER)
        t.append(["CC-001", "AWS Activate", "Sent", datetime(2026, 10, 1), datetime(2026, 10, 6), "Reply from programme lead",
                  "Eligible", "Asked for tier B"])  # fmt: skip
        t.append(["CC-002", "Rutgers", "Not contacted", None, None, None, None, None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _signals(data: bytes) -> list:
    cfg = load_configs()["capital_outreach"]
    ctx = FetchContext(min_interval_seconds=0, upload=data, upload_name="outreach.xlsx")
    return [normalize(cfg, raw) async for raw in get_adapter(cfg.adapter).fetch(cfg, ctx)]


async def test_tracker_sheet_details_join_by_prospect_id() -> None:
    first, second = await _signals(_workbook())
    a = first.attributes
    assert a["status"] == "Sent"  # the tracker sheet's Status wins over the flat import copy
    assert (a["first_sent_on"], a["next_action_on"]) == (date(2026, 10, 1), date(2026, 10, 6))
    assert tracker_values(first) == {
        "first_sent_on": date(2026, 10, 1), "next_action_on": date(2026, 10, 6),
        "reply_summary": "Reply from programme lead", "eligibility_decision": "Eligible", "notes": "Asked for tier B",
    }  # fmt: skip
    assert second.attributes["status"] == "Not contacted"
    assert set(tracker_values(second).values()) == {None}


async def test_workbook_without_tracker_sheet_still_imports() -> None:
    first, _ = await _signals(_workbook(tracker=False))
    assert first.attributes["status"] == "Not contacted"
    assert set(tracker_values(first).values()) == {None}
