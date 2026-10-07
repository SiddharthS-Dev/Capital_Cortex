"""Capital outreach register (FR-04-OUT): outreach research and tracker per opportunity, its append-only status
history, and the governed eligibility-gate register with human-confirmed links to opportunities.

Research fields are refreshed by a newer workbook import; tracker fields belong to people and are written by the
import only when the profile is first created (docs/OUTREACH.md, D-081…D-084).

Revision ID: 0007_outreach
Revises: 0006_fx_rates
Create Date: 2026-10-07
"""

from alembic import op

revision = "0007_outreach"
down_revision = "0006_fx_rates"
branch_labels = None
depends_on = None

DEFAULT_ORG = "00000000-0000-0000-0000-000000000001"

COMMON = f"""
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL DEFAULT '{DEFAULT_ORG}' REFERENCES tenant(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    is_demo boolean NOT NULL DEFAULT false"""

ROUTES = ["Contact now", "Conditional screen", "Eligibility gate first", "Watch next intake", "Later / portfolio route"]
ENGAGEMENT = ["High", "Medium", "Low", "Very low"]
STATUSES = [
    "Not contacted", "Prepared", "Sent", "Reply received", "Meeting booked", "Eligibility hold", "Applied", "Declined",
    "Won", "Watchlist",
]  # fmt: skip
GATE_STATUSES = ["open", "in_review", "cleared", "blocked", "not_applicable"]


def in_list(values: list[str]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


def provenance(table: str) -> str:
    """I1/I5: a non-empty source_ref (same rule as the knowledge tables in 0001)."""
    return f""",
    source_ref jsonb NOT NULL,
    CONSTRAINT ck_{table}_provenance CHECK (
        jsonb_typeof(source_ref) IN ('object', 'array') AND source_ref NOT IN ('{{}}'::jsonb, '[]'::jsonb))"""


TABLES = ["outreach_profile", "outreach_status_event", "eligibility_gate", "eligibility_gate_link"]


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE outreach_profile ({COMMON},
            opportunity_id uuid NOT NULL UNIQUE REFERENCES opportunity(id) ON DELETE CASCADE,
            -- research (refreshed by a newer import)
            prospect_id text,
            category text,
            route text CHECK (route IN ({in_list(ROUTES)})),
            engagement_outlook text CHECK (engagement_outlook IN ({in_list(ENGAGEMENT)})),
            cash_outlook text,
            relevance smallint CHECK (relevance BETWEEN 1 AND 5),
            accessibility smallint CHECK (accessibility BETWEEN 1 AND 5),
            readiness smallint CHECK (readiness BETWEEN 1 AND 5),
            analyst_priority smallint CHECK (analyst_priority BETWEEN 0 AND 100),
            priority_inconsistent boolean NOT NULL DEFAULT false,
            country_order smallint,
            country_rank smallint,
            contact_channel text,
            phones text[] NOT NULL DEFAULT '{{}}',
            official_source_url text,
            verified_on date,
            programme_status text,
            next_action text,
            proposed_owner_text text,
            import_status text,
            research_warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
            -- tracker (human-owned; the import sets them only on creation)
            outreach_status text NOT NULL DEFAULT 'Not contacted' CHECK (outreach_status IN ({in_list(STATUSES)})),
            first_sent_on date,
            next_action_on date,
            reply_summary text,
            eligibility_decision text,
            notes text,
            status_set_by text,
            status_set_at timestamptz{provenance("outreach_profile")}
        )""")
    op.execute(f"""
        CREATE TABLE outreach_status_event (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL DEFAULT '{DEFAULT_ORG}' REFERENCES tenant(id),
            is_demo boolean NOT NULL DEFAULT false,
            opportunity_id uuid NOT NULL REFERENCES opportunity(id) ON DELETE CASCADE,
            from_status text,
            to_status text NOT NULL CHECK (to_status IN ({in_list(STATUSES)})),
            actor text NOT NULL,
            at timestamptz NOT NULL DEFAULT now(),
            reason text
        )""")
    op.execute("""
        CREATE FUNCTION outreach_status_event_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'outreach_status_event is append-only (% blocked)', TG_OP; END $$""")
    op.execute("""
        CREATE TRIGGER trg_outreach_event_no_update BEFORE UPDATE OR DELETE ON outreach_status_event
        FOR EACH ROW EXECUTE FUNCTION outreach_status_event_immutable()""")
    op.execute("""
        CREATE TRIGGER trg_outreach_event_no_truncate BEFORE TRUNCATE ON outreach_status_event
        FOR EACH STATEMENT EXECUTE FUNCTION outreach_status_event_immutable()""")
    op.execute(f"""
        CREATE TABLE eligibility_gate ({COMMON},
            gate_code text NOT NULL,
            scope text,
            decision text,
            known_issue text,
            proposed_owner_text text,
            owner_id text,
            resolution_action text,
            affected_text text,
            status text NOT NULL DEFAULT 'open' CHECK (status IN ({in_list(GATE_STATUSES)})),
            UNIQUE (org_id, gate_code){provenance("eligibility_gate")}
        )""")
    op.execute(f"""
        CREATE TABLE eligibility_gate_link (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL DEFAULT '{DEFAULT_ORG}' REFERENCES tenant(id),
            is_demo boolean NOT NULL DEFAULT false,
            gate_id uuid NOT NULL REFERENCES eligibility_gate(id) ON DELETE CASCADE,
            opportunity_id uuid NOT NULL REFERENCES opportunity(id) ON DELETE CASCADE,
            linked_by text NOT NULL,
            linked_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (gate_id, opportunity_id)
        )""")
    for stmt in (
        "CREATE INDEX ix_outreach_status ON outreach_profile (org_id, outreach_status)",
        "CREATE INDEX ix_outreach_route ON outreach_profile (org_id, route)",
        "CREATE INDEX ix_outreach_next_action ON outreach_profile (org_id, next_action_on)",
        "CREATE INDEX ix_outreach_event_opp ON outreach_status_event (opportunity_id, at)",
        "CREATE INDEX ix_gate_link_opp ON eligibility_gate_link (opportunity_id)",
    ):
        op.execute(stmt)
    for t in ("outreach_profile", "eligibility_gate"):
        op.execute(
            f"CREATE TRIGGER trg_{t}_updated BEFORE UPDATE ON {t} FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )
    op.execute(f"GRANT SELECT ON {', '.join(TABLES)} TO cortex_readonly")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS outreach_status_event_immutable()")
