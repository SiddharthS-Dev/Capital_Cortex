"""Exchange rates: daily ECB euro reference rates, so the weighted pipeline can show one combined total.

Amounts stay stored in their own currency; conversion only happens when a combined figure is displayed, and
that figure names the rate date and source.

Revision ID: 0006_fx_rates
Revises: 0005_load_indexes
Create Date: 2026-10-02
"""

from alembic import op

revision = "0006_fx_rates"
down_revision = "0005_load_indexes"
branch_labels = None
depends_on = None

DEFAULT_ORG = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE fx_rate (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL DEFAULT '{DEFAULT_ORG}' REFERENCES tenant(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            is_demo boolean NOT NULL DEFAULT false,
            rate_date date NOT NULL,
            base char(3) NOT NULL,
            quote char(3) NOT NULL,
            rate numeric(20, 10) NOT NULL CHECK (rate > 0),
            source text NOT NULL,
            UNIQUE (org_id, rate_date, base, quote)
        )
    """)
    op.execute("CREATE INDEX ix_fx_rate_latest ON fx_rate (org_id, base, rate_date DESC)")
    op.execute(
        "CREATE TRIGGER trg_fx_rate_updated BEFORE UPDATE ON fx_rate FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute("GRANT SELECT ON fx_rate TO cortex_readonly")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fx_rate CASCADE")
