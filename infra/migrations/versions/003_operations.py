"""Service fencing and durable storage cleanup."""

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"


def upgrade():
    op.create_table(
        "service_leases",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("token", sa.String(36), nullable=False),
        sa.Column("expires", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "cleanup_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant", sa.String(80), nullable=False),
        sa.Column("keys", sa.JSON(), nullable=False),
        sa.Column("prefixes", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(80)),
        sa.Column("created", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_cleanup_tasks_tenant", "cleanup_tasks", ["tenant"])


def downgrade():
    op.drop_table("cleanup_tasks")
    op.drop_table("service_leases")
