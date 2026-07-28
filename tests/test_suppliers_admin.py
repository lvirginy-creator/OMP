from sqlalchemy import select

from app.models.mapping import Mapping
from app.models.supplier import Supplier, SupplierAlias
from app.services.suppliers import get_or_create_supplier, now_iso


async def test_rename_supplier(client, db_session):
    supplier = await get_or_create_supplier(db_session, "Nom Avant SAS")
    await db_session.commit()
    supplier_id = supplier.id

    resp = client.post(
        f"/referentiel/fournisseurs/{supplier_id}/rename",
        data={"name": "Nom Après SAS"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    listing = client.get("/referentiel")
    assert "Nom Après SAS" in listing.text


async def test_merge_suppliers_reassigns_and_creates_alias(client, db_session):
    keep = await get_or_create_supplier(db_session, "Fournisseur Principal SAS")
    absorbed = await get_or_create_supplier(db_session, "Fournisseur Doublon SAS")
    timestamp = now_iso()
    db_session.add(
        Mapping(
            supplier_id=absorbed.id,
            supplier_ref="MERGEREF-1",
            our_ref="INT-MERGE-1",
            our_label="Article fusionné",
            active=True,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    await db_session.commit()
    keep_id, absorbed_id = keep.id, absorbed.id
    absorbed_normalized = absorbed.normalized_name

    resp = client.post(
        f"/referentiel/fournisseurs/{absorbed_id}/merge",
        data={"target_id": keep_id},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db_session.expire_all()
    remaining = await db_session.get(Supplier, absorbed_id)
    assert remaining is None

    mapping = (
        await db_session.execute(select(Mapping).where(Mapping.supplier_ref == "MERGEREF-1"))
    ).scalar_one()
    assert mapping.supplier_id == keep_id

    alias = (
        await db_session.execute(
            select(SupplierAlias).where(SupplierAlias.normalized_alias == absorbed_normalized)
        )
    ).scalar_one_or_none()
    assert alias is not None
    assert alias.supplier_id == keep_id
