"""Revocable sessions, shared rate limits and worker fencing/outbox."""

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"


def upgrade():
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("expires", sa.DateTime(), nullable=False),
        sa.Column("revoked", sa.Integer(), nullable=False),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table(
        "rate_buckets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "dispatch",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sent", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )
    op.create_table(
        "worker_leases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token", sa.String(36), nullable=False),
    )


def downgrade():
    for table in ("worker_leases", "dispatch", "rate_buckets", "auth_sessions"):
        op.drop_table(table)
