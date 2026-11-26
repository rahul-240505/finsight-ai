"""transactions and idempotency

Revision ID: 878364da44cb
Revises: f33d7f343f7b
Create Date: 2026-11-26 19:03:33.435148

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "878364da44cb"
down_revision: str | Sequence[str] | None = "f33d7f343f7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # datasets first: the composite FK on transactions needs UNIQUE(id, owner_id) to exist.
    op.add_column(
        "datasets",
        sa.Column("status", sa.String(length=20), server_default="imported", nullable=False),
    )
    op.add_column(
        "datasets", sa.Column("row_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("datasets", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_datasets_id_owner", "datasets", ["id", "owner_id"])
    op.create_unique_constraint(
        "uq_datasets_owner_content", "datasets", ["owner_id", "content_hash"]
    )
    # Not detected by autogenerate (CHECKs on existing tables): added by hand.
    op.create_check_constraint(
        op.f("ck_datasets_status_valid"), "datasets", "status IN ('imported')"
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("external_ref", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("merchant", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_transactions_currency_iso")),
        sa.ForeignKeyConstraint(
            ["dataset_id", "owner_id"],
            ["datasets.id", "datasets.owner_id"],
            name="fk_transactions_dataset_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
        sa.UniqueConstraint("dataset_id", "external_ref", name="uq_transactions_dataset_ref"),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_idempotency_records_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_records")),
        sa.UniqueConstraint("user_id", "key", name="uq_idempotency_user_key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_table("transactions")
    op.drop_constraint(op.f("ck_datasets_status_valid"), "datasets", type_="check")
    op.drop_constraint("uq_datasets_owner_content", "datasets", type_="unique")
    op.drop_constraint("uq_datasets_id_owner", "datasets", type_="unique")
    op.drop_column("datasets", "content_hash")
    op.drop_column("datasets", "row_count")
    op.drop_column("datasets", "status")
