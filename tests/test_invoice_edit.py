import json

from app.models.invoice import Invoice
from app.services import invoice_pipeline
from app.services.anomalies import can_validate
from app.services.invoice_edit import delete_invoice, force_validate, save_invoice_edits
from app.services.suppliers import now_iso
from tests.fixtures.pdf_builder import simple_invoice_pdf


async def _create_manual_invoice(db_session) -> Invoice:
    """Crée une facture via le pipeline sans clé API -> extraction_method MANUAL, 0 ligne."""
    result = await invoice_pipeline.process_uploaded_pdf(
        db_session, "manuelle.pdf", simple_invoice_pdf()
    )
    assert result.outcome == "CREATED"
    invoice = await db_session.get(Invoice, result.invoice_id)
    await db_session.refresh(invoice, attribute_names=["lines"])
    return invoice


async def test_can_validate_blocks_on_total_mismatch_and_missing_field():
    assert can_validate([]) is True
    assert can_validate(["A_LOW_CONFIDENCE", "A_UNMAPPED_REF"]) is True
    assert can_validate(["A_TOTAL_MISMATCH"]) is False
    assert can_validate(["A_MISSING_FIELD"]) is False


async def test_save_invoice_edits_fills_missing_fields_and_recomputes_status(db_session):
    invoice = await _create_manual_invoice(db_session)
    assert invoice.status == "NEEDS_REVIEW"

    header = {
        "supplier_name": "Nouveau Fournisseur SAS",
        "document_type": "INVOICE",
        "invoice_number": "F-MANUEL-1",
        "invoice_date": "2026-02-01",
        "currency": "EUR",
        "total_ht": 100.0,
        "total_vat": 20.0,
        "total_ttc": 120.0,
    }
    lines = [
        {
            "line_type": "ARTICLE",
            "charge_kind": None,
            "supplier_ref": "REF-1",
            "supplier_label": "Article saisi à la main",
            "quantity": 10.0,
            "unit_price_net": 10.0,
            "line_total_net": 100.0,
        }
    ]

    result = await save_invoice_edits(db_session, invoice, header, lines)
    assert result.ok is True

    await db_session.refresh(invoice, attribute_names=["lines"])
    assert invoice.invoice_number == "F-MANUEL-1"
    assert len(invoice.lines) == 1
    assert invoice.lines[0].supplier_label == "Article saisi à la main"
    # A_UNMAPPED_REF reste (pas de mapping créé) mais ne bloque pas le statut auto ici
    # car compute_anomalies traite tout sauf A_NEW_SUPPLIER comme bloquant -> NEEDS_REVIEW.
    assert invoice.status == "NEEDS_REVIEW"
    codes = json.loads(invoice.anomalies)
    assert "A_MISSING_FIELD" not in codes
    assert "A_NO_LINES" not in codes


async def test_save_invoice_edits_conflicting_business_key_is_rejected(db_session):
    from app.services.suppliers import get_or_create_supplier

    supplier = await get_or_create_supplier(db_session, "Fournisseur Conflit SAS")
    await db_session.commit()

    other = await _create_manual_invoice(db_session)
    other.supplier_id = supplier.id
    other.invoice_number = "DUP-1"
    other.document_type = "INVOICE"
    await db_session.commit()

    invoice = await _create_manual_invoice(db_session)
    header = {
        "supplier_name": "Fournisseur Conflit SAS",
        "document_type": "INVOICE",
        "invoice_number": "DUP-1",
        "invoice_date": "2026-02-01",
        "currency": "EUR",
        "total_ht": 10.0,
        "total_vat": 0.0,
        "total_ttc": 10.0,
    }
    result = await save_invoice_edits(db_session, invoice, header, [])
    assert result.ok is False
    assert "DUP-1" in result.message


async def test_force_validate_blocked_by_total_mismatch(db_session):
    invoice = await _create_manual_invoice(db_session)
    invoice.anomalies = json.dumps(["A_TOTAL_MISMATCH"])
    await db_session.commit()

    result = await force_validate(db_session, invoice)
    assert result.ok is False
    assert invoice.status == "NEEDS_REVIEW"


async def test_force_validate_succeeds_when_not_blocked(db_session):
    invoice = await _create_manual_invoice(db_session)
    invoice.anomalies = json.dumps(["A_UNMAPPED_REF", "A_LOW_CONFIDENCE"])
    await db_session.commit()

    result = await force_validate(db_session, invoice)
    assert result.ok is True
    assert invoice.status == "VALIDATED"
    assert invoice.validated_at is not None


async def test_delete_invoice_moves_pdf_to_trash_and_logs(db_session, tmp_path):
    invoice = await _create_manual_invoice(db_session)
    invoice_id = invoice.id
    stored_path = invoice.stored_path

    deleted_dir = tmp_path / "deleted"
    await delete_invoice(db_session, invoice, deleted_dir)

    from pathlib import Path

    assert not Path(stored_path).exists()
    moved = deleted_dir / Path(stored_path).name
    assert moved.exists()

    from sqlalchemy import select

    from app.models.import_log import ImportLog

    remaining = await db_session.get(Invoice, invoice_id)
    assert remaining is None

    log_entries = (
        await db_session.execute(select(ImportLog).where(ImportLog.outcome == "DELETED"))
    ).scalars().all()
    assert any(str(invoice_id) in (e.message or "") for e in log_entries)
