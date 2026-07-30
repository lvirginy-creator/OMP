"""ajoute la taille (size) sur invoice_lines et mappings

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("invoice_lines") as batch_op:
        batch_op.add_column(sa.Column("size", sa.String(16)))

    with op.batch_alter_table("mappings") as batch_op:
        batch_op.add_column(sa.Column("size", sa.String(16)))

    op.execute("DROP INDEX IF EXISTS ux_mapping")
    op.execute(
        "CREATE UNIQUE INDEX ux_mapping ON mappings "
        "(IFNULL(supplier_id, -1), supplier_ref_norm, IFNULL(size, ''))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_mapping")
    op.execute(
        "CREATE UNIQUE INDEX ux_mapping ON mappings (IFNULL(supplier_id, -1), supplier_ref_norm)"
    )

    with op.batch_alter_table("mappings") as batch_op:
        batch_op.drop_column("size")

    with op.batch_alter_table("invoice_lines") as batch_op:
        batch_op.drop_column("size")
