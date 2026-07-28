from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)

    aliases: Mapped[list["SupplierAlias"]] = relationship(
        back_populates="supplier", cascade="all, delete-orphan"
    )


class SupplierAlias(Base):
    __tablename__ = "supplier_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    normalized_alias: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    supplier: Mapped["Supplier"] = relationship(back_populates="aliases")
