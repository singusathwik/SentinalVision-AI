"""Initial schema; use alembic -c infra/alembic.ini upgrade head."""

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None


def upgrade():
    op.create_table(
        "records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_records_tenant", "records", ["tenant"])
    op.create_index("ix_records_kind", "records", ["kind"])
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("tenant", sa.String(80), nullable=False),
        sa.Column("password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant", sa.String(80), nullable=False),
        sa.Column("video_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(1000)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease", sa.DateTime()),
        sa.Column("created", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_jobs_tenant", "jobs", ["tenant"])
    op.create_index("ix_jobs_state", "jobs", ["state"])


def downgrade():
    op.drop_table("jobs")
    op.drop_table("users")
    op.drop_table("records")
