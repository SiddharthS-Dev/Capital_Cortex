"""Build-phase registry (§16). The API exposes this through /v1/meta so the UI can show "Coming in Phase n".

CURRENT_PHASE is the last phase whose definition of done is met.
"""

CURRENT_PHASE = 3

# feature key → phase in which it becomes available
FEATURE_PHASES: dict[str, int] = {
    # screens (§9)
    "screen.command_center": 1,
    "screen.radar": 1,
    "screen.opportunity_detail": 1,
    "screen.scoring_studio": 1,
    "screen.graph_explorer": 1,
    "screen.relationships": 2,
    "screen.agent_council": 2,
    "screen.proposal_factory": 3,
    "screen.data_room": 3,
    "screen.forecast_studio": 1,  # basic in Phase 1, full in Phase 3
    "screen.grant_calendar": 2,
    "screen.approvals": 2,
    "screen.alerts": 2,
    "screen.board_reports": 3,
    "screen.sources": 1,
    "screen.audit": 0,  # log search + chain verify ship in Phase 0; retention/legal hold in Phase 3
    "screen.admin": 3,
    "screen.copilot": 3,
    # capital outreach register (FR-04-OUT, docs/OUTREACH.md)
    "outreach.tab": 3,
    "outreach.tracker": 3,
    "eligibility_gates": 3,
    # cross-cutting
    "approval_badge": 0,  # reads the real approval table (empty until Phase 2 creates approvals)
    "alerts_bell": 2,
    "budget_meter": 0,
    "command_palette": 0,
}
