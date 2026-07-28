"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("normalized_name", sa.Text, nullable=False, unique=True),
        sa.Column("created_at", sa.String(32), nullable=False),
    )

    op.create_table(
        "supplier_aliases",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "supplier_id",
            sa.Integer,
            sa.ForeignKey("suppliers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("normalized_alias", sa.Text, nullable=False, unique=True),
    )

    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("supplier_id", sa.Integer, sa.ForeignKey("suppliers.id")),
        sa.Column("document_type", sa.String(16), nullable=False),
        sa.Column("invoice_number", sa.Text),
        sa.Column("invoice_date", sa.String(10)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("total_ht", sa.Float),
        sa.Column("total_vat", sa.Float),
        sa.Column("total_ttc", sa.Float),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("extraction_method", sa.String(24), nullable=False),
        sa.Column("doc_class", sa.String(8)),
        sa.Column("raw_diagnostics", sa.Text),
        sa.Column("source_filename", sa.Text, nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("stored_path", sa.Text, nullable=False),
        sa.Column("anomalies", sa.Text),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("validated_at", sa.String(32)),
    )
    op.create_index(
        "ux_invoice_business_key",
        "invoices",
        ["supplier_id", "invoice_number", "document_type"],
        unique=True,
        sqlite_where=sa.text("invoice_number IS NOT NULL"),
    )
    op.create_index("ix_invoices_hash", "invoices", ["file_hash"])
    op.create_index("ix_invoices_date", "invoices", ["invoice_date"])

    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "invoice_id",
            sa.Integer,
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("line_type", sa.String(8), nullable=False),
        sa.Column("charge_kind", sa.String(16)),
        sa.Column("supplier_ref", sa.Text),
        sa.Column(
            "supplier_ref_norm",
            sa.Text,
            sa.Computed(
                "UPPER(REPLACE(REPLACE(supplier_ref, ' ', ''), '-', ''))", persisted=True
            ),
        ),
        sa.Column("supplier_label", sa.Text),
        sa.Column("quantity", sa.Float),
        sa.Column("unit_price_net", sa.Float),
        sa.Column("line_total_net", sa.Float),
        sa.Column("vat_rate", sa.Float),
        sa.Column("raw", sa.Text),
    )
    op.create_index("ix_lines_ref", "invoice_lines", ["supplier_ref_norm"])

    op.create_table(
        "mappings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("supplier_id", sa.Integer, sa.ForeignKey("suppliers.id")),
        sa.Column("supplier_ref", sa.Text, nullable=False),
        sa.Column(
            "supplier_ref_norm",
            sa.Text,
            sa.Computed(
                "UPPER(REPLACE(REPLACE(supplier_ref, ' ', ''), '-', ''))", persisted=True
            ),
        ),
        sa.Column("supplier_label", sa.Text),
        sa.Column("our_ref", sa.Text, nullable=False),
        sa.Column("our_label", sa.Text, nullable=False),
        sa.Column("ean", sa.String(32)),
        sa.Column("active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_mapping ON mappings (IFNULL(supplier_id, -1), supplier_ref_norm)"
    )

    op.create_table(
        "import_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("file_hash", sa.String(64)),
        sa.Column(
            "invoice_id", sa.Integer, sa.ForeignKey("invoices.id", ondelete="SET NULL")
        ),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("message", sa.Text),
        sa.Column("created_at", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("import_log")
    op.execute("DROP INDEX IF EXISTS ux_mapping")
    op.drop_table("mappings")
    op.drop_index("ix_lines_ref", table_name="invoice_lines")
    op.drop_table("invoice_lines")
    op.drop_index("ix_invoices_date", table_name="invoices")
    op.drop_index("ix_invoices_hash", table_name="invoices")
    op.drop_index("ux_invoice_business_key", table_name="invoices")
    op.drop_table("invoices")
    op.drop_table("supplier_aliases")
    op.drop_table("suppliers")
