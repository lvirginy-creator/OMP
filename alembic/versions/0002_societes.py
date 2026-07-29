"""ajoute la table societes et invoices.societe_id

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "societes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(32), nullable=False),
    )

    with op.batch_alter_table("invoices") as batch_op:
        batch_op.add_column(
            sa.Column(
                "societe_id",
                sa.Integer,
                sa.ForeignKey("societes.id", name="fk_invoices_societe_id"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("invoices") as batch_op:
        batch_op.drop_column("societe_id")
    op.drop_table("societes")
