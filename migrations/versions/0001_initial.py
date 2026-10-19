"""Initial portable tables; immutable migration independent of current ORM models."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenders",
        sa.Column("tender_id", sa.String(64), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "enrichment_runs",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("tender_id", sa.String(64), sa.ForeignKey("tenders.tender_id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_runs_tender_processed", "enrichment_runs", ["tender_id", "processed_at"])
    op.create_table(
        "company_profiles",
        sa.Column(
            "run_id", sa.String(36), sa.ForeignKey("enrichment_runs.run_id"), primary_key=True
        ),
        sa.Column("company_name", sa.Text()),
        sa.Column("phone", sa.String(100)),
        sa.Column("email", sa.Text()),
        sa.Column("website", sa.Text()),
        sa.Column("address", sa.Text()),
        sa.Column("city", sa.String(100)),
        sa.Column("district", sa.String(100)),
        sa.Column("mersis_no", sa.String(16)),
        sa.Column("trade_registry_no", sa.String(100)),
        sa.Column("trade_registry_office", sa.Text()),
        sa.Column("tax_no", sa.String(10)),
        sa.Column("tax_office", sa.Text()),
    )
    op.create_table(
        "sources",
        sa.Column("source_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("enrichment_runs.run_id"), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "evidence",
        sa.Column("evidence_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("enrichment_runs.run_id"), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("sources.source_id"), nullable=False),
        sa.Column("field", sa.String(64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    for table in ("evidence", "sources", "company_profiles", "enrichment_runs", "tenders"):
        op.drop_table(table)
