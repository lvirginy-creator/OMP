from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mapping import Mapping
from app.services.normalize import normalize_ref


async def resolve_mapping(
    db: AsyncSession, supplier_id: int | None, supplier_ref: str | None
) -> Mapping | None:
    """Résolution §4 : spécifique au fournisseur > global > absent."""
    ref_norm = normalize_ref(supplier_ref or "")
    if not ref_norm:
        return None

    if supplier_id:
        stmt = select(Mapping).where(
            Mapping.supplier_ref_norm == ref_norm,
            Mapping.supplier_id == supplier_id,
            Mapping.active.is_(True),
        )
        result = (await db.execute(stmt)).scalar_one_or_none()
        if result:
            return result

    stmt = select(Mapping).where(
        Mapping.supplier_ref_norm == ref_norm,
        Mapping.supplier_id.is_(None),
        Mapping.active.is_(True),
    )
    return (await db.execute(stmt)).scalar_one_or_none()
