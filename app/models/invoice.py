from sqlalchemy import Computed, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    societe_id: Mapped[int | None] = mapped_column(ForeignKey("societes.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    document_type: Mapped[str] = mapped_column(String(16), nullable=False)  # INVOICE | CREDIT_NOTE
    invoice_number: Mapped[str | None] = mapped_column(Text)
    invoice_date: Mapped[str | None] = mapped_column(String(10))  # ISO YYYY-MM-DD
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    total_ht: Mapped[float | None] = mapped_column(Float)
    total_vat: Mapped[float | None] = mapped_column(Float)
    total_ttc: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # NEEDS_REVIEW | VALIDATED
    extraction_method: Mapped[str] = mapped_column(String(24), nullable=False)
    doc_class: Mapped[str | None] = mapped_column(String(8))  # TEXTE | SCAN | MIXTE
    raw_diagnostics: Mapped[str | None] = mapped_column(Text)
    source_filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    anomalies: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    validated_at: Mapped[str | None] = mapped_column(String(32))

    supplier: Mapped["object | None"] = relationship("Supplier")
    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceLine.line_no"
    )

    __table_args__ = (
        Index(
            "ux_invoice_business_key",
            "supplier_id",
            "invoice_number",
            "document_type",
            unique=True,
            sqlite_where=text("invoice_number IS NOT NULL"),
        ),
        Index("ix_invoices_hash", "file_hash"),
        Index("ix_invoices_date", "invoice_date"),
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    line_type: Mapped[str] = mapped_column(String(8), nullable=False)  # ARTICLE | CHARGE
    charge_kind: Mapped[str | None] = mapped_column(String(16))
    supplier_ref: Mapped[str | None] = mapped_column(Text)
    supplier_ref_norm: Mapped[str | None] = mapped_column(
        Text,
        Computed("UPPER(REPLACE(REPLACE(supplier_ref, ' ', ''), '-', ''))", persisted=True),
    )
    supplier_label: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float | None] = mapped_column(Float)
    unit_price_net: Mapped[float | None] = mapped_column(Float)
    line_total_net: Mapped[float | None] = mapped_column(Float)
    vat_rate: Mapped[float | None] = mapped_column(Float)
    raw: Mapped[str | None] = mapped_column(Text)  # JSON brut, inclut notamment "low_confidence"

    invoice: Mapped["Invoice"] = relationship(back_populates="lines")

    __table_args__ = (Index("ix_lines_ref", "supplier_ref_norm"),)
