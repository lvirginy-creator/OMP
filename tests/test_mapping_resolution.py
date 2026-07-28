from app.models.mapping import Mapping
from app.services.mapping_resolution import resolve_mapping
from app.services.suppliers import get_or_create_supplier, now_iso


async def test_resolution_prefers_specific_over_global_over_absent(db_session):
    supplier = await get_or_create_supplier(db_session, "Fournisseur Résolution SAS")
    timestamp = now_iso()

    assert await resolve_mapping(db_session, supplier.id, "REF-X") is None

    db_session.add(
        Mapping(
            supplier_id=None,
            supplier_ref="REF-X",
            our_ref="GLOBAL-X",
            our_label="Global X",
            active=True,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    await db_session.commit()

    global_match = await resolve_mapping(db_session, supplier.id, "REF-X")
    assert global_match is not None
    assert global_match.our_ref == "GLOBAL-X"

    db_session.add(
        Mapping(
            supplier_id=supplier.id,
            supplier_ref="REF-X",
            our_ref="SPECIFIC-X",
            our_label="Spécifique X",
            active=True,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    await db_session.commit()

    specific_match = await resolve_mapping(db_session, supplier.id, "REF-X")
    assert specific_match.our_ref == "SPECIFIC-X"

    other_supplier = await get_or_create_supplier(db_session, "Autre Fournisseur SAS")
    other_match = await resolve_mapping(db_session, other_supplier.id, "REF-X")
    assert other_match.our_ref == "GLOBAL-X"  # pas de mapping spécifique pour cet autre fournisseur


async def test_resolution_ignores_inactive_mappings(db_session):
    supplier = await get_or_create_supplier(db_session, "Fournisseur Inactif SAS")
    timestamp = now_iso()
    db_session.add(
        Mapping(
            supplier_id=supplier.id,
            supplier_ref="REF-Y",
            our_ref="Y",
            our_label="Y",
            active=False,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    await db_session.commit()

    assert await resolve_mapping(db_session, supplier.id, "REF-Y") is None


async def test_resolution_normalizes_reference_variants(db_session):
    supplier = await get_or_create_supplier(db_session, "Fournisseur Normalise SAS")
    timestamp = now_iso()
    db_session.add(
        Mapping(
            supplier_id=supplier.id,
            supplier_ref="abc-123",
            our_ref="Z",
            our_label="Z",
            active=True,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    await db_session.commit()

    assert await resolve_mapping(db_session, supplier.id, "ABC 123") is not None
    assert await resolve_mapping(db_session, supplier.id, " abc123 ") is not None
