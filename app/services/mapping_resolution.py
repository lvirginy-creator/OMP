from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mapping import Mapping
from app.services.normalize import normalize_ref, normalize_size


async def resolve_mapping(
    db: AsyncSession, supplier_id: int | None, supplier_ref: str | None, size: str | None = None
) -> Mapping | None:
    """Résolution §4 : spécifique au fournisseur > global > absent.
    Si l'article est décliné en tailles, la taille fait partie de la clé de résolution
    (une taille = potentiellement une référence interne différente)."""
    ref_norm = normalize_ref(supplier_ref or "")
    if not ref_norm:
        return None
    size_norm = normalize_size(size)
    size_filter = Mapping.size.is_(None) if size_norm is None else Mapping.size == size_norm

    if supplier_id:
        stmt = select(Mapping).where(
            Mapping.supplier_ref_norm == ref_norm,
            Mapping.supplier_id == supplier_id,
            size_filter,
            Mapping.active.is_(True),
        )
        result = (await db.execute(stmt)).scalar_one_or_none()
        if result:
            return result

    stmt = select(Mapping).where(
        Mapping.supplier_ref_norm == ref_norm,
        Mapping.supplier_id.is_(None),
        size_filter,
        Mapping.active.is_(True),
    )
    return (await db.execute(stmt)).scalar_one_or_none()
