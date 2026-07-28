from sqlalchemy import Boolean, Computed, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Mapping(Base):
    __tablename__ = "mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    supplier_ref: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_ref_norm: Mapped[str] = mapped_column(
        Text,
        Computed("UPPER(REPLACE(REPLACE(supplier_ref, ' ', ''), '-', ''))", persisted=True),
    )
    supplier_label: Mapped[str | None] = mapped_column(Text)
    our_ref: Mapped[str] = mapped_column(Text, nullable=False)
    our_label: Mapped[str] = mapped_column(Text, nullable=False)
    ean: Mapped[str | None] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        Index(
            "ux_mapping",
            text("IFNULL(supplier_id, -1)"),
            "supplier_ref_norm",
            unique=True,
        ),
    )
