from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supplier import Supplier, SupplierAlias
from app.services.normalize import normalize_supplier_name


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_or_create_supplier(db: AsyncSession, name: str) -> Supplier:
    """Résout un fournisseur par nom normalisé ou alias ; le crée si inconnu."""
    normalized = normalize_supplier_name(name)

    result = await db.execute(select(Supplier).where(Supplier.normalized_name == normalized))
    supplier = result.scalar_one_or_none()
    if supplier:
        return supplier

    result = await db.execute(
        select(SupplierAlias).where(SupplierAlias.normalized_alias == normalized)
    )
    alias = result.scalar_one_or_none()
    if alias:
        result = await db.execute(select(Supplier).where(Supplier.id == alias.supplier_id))
        return result.scalar_one()

    supplier = Supplier(name=name.strip(), normalized_name=normalized, created_at=now_iso())
    db.add(supplier)
    await db.flush()
    return supplier


async def merge_suppliers(db: AsyncSession, keep_id: int, absorbed_id: int) -> None:
    """Fusionne absorbed_id dans keep_id : réaffecte factures/mappings, crée un alias."""
    if keep_id == absorbed_id:
        return

    absorbed = await db.get(Supplier, absorbed_id)
    if absorbed is None:
        return

    from app.models.invoice import Invoice
    from app.models.mapping import Mapping

    for model in (Invoice, Mapping):
        result = await db.execute(select(model).where(model.supplier_id == absorbed_id))
        for row in result.scalars():
            row.supplier_id = keep_id

    existing_alias = await db.execute(
        select(SupplierAlias).where(SupplierAlias.normalized_alias == absorbed.normalized_name)
    )
    if existing_alias.scalar_one_or_none() is None:
        db.add(SupplierAlias(supplier_id=keep_id, normalized_alias=absorbed.normalized_name))

    for alias in absorbed.aliases:
        alias.supplier_id = keep_id

    await db.delete(absorbed)
