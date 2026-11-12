"""export approval binding columns, offboarding step order, extra statuses

Revision ID: 0002_flows
Revises: 0002 (work)
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_flows"
down_revision = "0002"
branch_labels = None
depends_on = None

OLD_EXPORT = "'requested', 'reviewed', 'approved', 'rejected', 'staged', 'released', 'expired'"
NEW_EXPORT = OLD_EXPORT + ", 'cancelled'"
OLD_STEP = "'pending', 'running', 'succeeded', 'failed', 'manual_required', 'verified'"
NEW_STEP = OLD_STEP + ", 'skipped_not_configured'"


def _swap(table: str, name: str, values: str) -> None:
    cname = op.f(f"ck_{table}_{name}")  # op.f: already the final name, skip the naming convention
    op.drop_constraint(cname, table, type_="check")
    op.create_check_constraint(cname, table, f"{name} IN ({values})")


def upgrade() -> None:
    op.add_column("export_requests", sa.Column("object_checksum", sa.Text(), nullable=True))
    op.add_column("export_requests", sa.Column("approval_digest", sa.Text(), nullable=True))
    op.add_column("export_requests", sa.Column("staged_path", sa.Text(), nullable=True))
    op.add_column("export_requests", sa.Column("stage_error", sa.Text(), nullable=True))
    op.add_column(
        "offboarding_steps",
        sa.Column("seq", sa.Integer(), server_default="0", nullable=False),
    )
    _swap("export_requests", "status", NEW_EXPORT)
    _swap("offboarding_steps", "status", NEW_STEP)


def downgrade() -> None:
    _swap("offboarding_steps", "status", OLD_STEP)
    _swap("export_requests", "status", OLD_EXPORT)
    op.drop_column("offboarding_steps", "seq")
    for col in ("stage_error", "staged_path", "approval_digest", "object_checksum"):
        op.drop_column("export_requests", col)
