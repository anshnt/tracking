"""unique employee email, workspace asset link, maintenance exceptions

Revision ID: 0003
Revises: 0002_flows
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002_flows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # keep the oldest row per case-insensitive email; blank the rest (same as provisioning does)
    op.execute(
        "UPDATE employees SET email = '' WHERE email <> '' AND id IN ("
        "SELECT id FROM (SELECT id, row_number() OVER ("
        "PARTITION BY lower(email) ORDER BY created_at, id) AS rn FROM employees "
        "WHERE email <> '') t WHERE rn > 1)"
    )
    op.drop_index("ix_employees_email", table_name="employees")
    op.create_index(
        "uq_employees_email_lower",
        "employees",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email <> ''"),
    )
    op.add_column("workspaces", sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_workspaces_asset_id_assets"), "workspaces", "assets", ["asset_id"], ["id"]
    )
    op.create_table(
        "maintenance_exceptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approver_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "approver_id <> requested_by",
            name=op.f("ck_maintenance_exceptions_approver_not_requester"),
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.id"], name=op.f("fk_maintenance_exceptions_asset_id_assets")
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["employees.id"],
            name=op.f("fk_maintenance_exceptions_requested_by_employees"),
        ),
        sa.ForeignKeyConstraint(
            ["approver_id"],
            ["employees.id"],
            name=op.f("fk_maintenance_exceptions_approver_id_employees"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maintenance_exceptions")),
    )
    op.create_index(
        "ix_maintenance_exceptions_asset_expires",
        "maintenance_exceptions",
        ["asset_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_table("maintenance_exceptions")
    op.drop_constraint(op.f("fk_workspaces_asset_id_assets"), "workspaces", type_="foreignkey")
    op.drop_column("workspaces", "asset_id")
    op.drop_index("uq_employees_email_lower", table_name="employees")
    op.create_index("ix_employees_email", "employees", ["email"])
