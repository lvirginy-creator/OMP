import json
import uuid

from app.models.invoice import Invoice, InvoiceLine
from app.services.anomalies import compute_anomalies, status_from_anomalies
from app.services.suppliers import get_or_create_supplier, now_iso


async def _make_invoice(db_session, **overrides) -> Invoice:
    defaults = dict(
        supplier_id=None,
        document_type="INVOICE",
        invoice_number="F-ANOM-1",
        invoice_date="2026-06-01",
        currency="EUR",
        total_ht=100.0,
        total_vat=20.0,
        total_ttc=120.0,
        status="NEEDS_REVIEW",
        extraction_method="NATIVE_LLM",
        doc_class="TEXTE",
        source_filename="f.pdf",
        file_hash="hash-" + uuid.uuid4().hex,
        stored_path="/data/pdfs/x.pdf",
        created_at=now_iso(),
    )
    defaults.update(overrides)
    invoice = Invoice(**defaults)
    db_session.add(invoice)
    await db_session.flush()
    return invoice


def _add_line(db_session, invoice, **overrides):
    defaults = dict(
        invoice_id=invoice.id,
        line_no=1,
        line_type="ARTICLE",
        supplier_ref="REF-ANOM-1",
        supplier_label="Article",
        quantity=10.0,
        unit_price_net=10.0,
        line_total_net=100.0,
        raw=json.dumps({}),
    )
    defaults.update(overrides)
    line = InvoiceLine(**defaults)
    db_session.add(line)
    return line


async def test_a_no_lines(db_session):
    invoice = await _make_invoice(db_session)
    await db_session.flush()
    await db_session.refresh(invoice, attribute_names=["lines"])
    codes = await compute_anomalies(db_session, invoice, "Fournisseur", False)
    assert "A_NO_LINES" in codes


async def test_a_total_mismatch(db_session):
    invoice = await _make_invoice(db_session, total_ht=100.0)
    _add_line(db_session, invoice, line_total_net=50.0)
    await db_session.flush()
    await db_session.refresh(invoice, attribute_names=["lines"])
    codes = await compute_anomalies(db_session, invoice, "Fournisseur", False)
    assert "A_TOTAL_MISMATCH" in codes


async def test_no_total_mismatch_within_tolerance(db_session):
    invoice = await _make_invoice(db_session, total_ht=100.0)
    _add_line(db_session, invoice, line_total_net=99.99)
    await db_session.flush()
    await db_session.refresh(invoice, attribute_names=["lines"])
    codes = await compute_anomalies(db_session, invoice, "Fournisseur", False)
    assert "A_TOTAL_MISMATCH" not in codes


async def test_a_missing_field_supplier_name(db_session):
    invoice = await _make_invoice(db_session)
    _add_line(db_session, invoice)
    await db_session.flush()
    await db_session.refresh(invoice, attribute_names=["lines"])
    codes = await compute_anomalies(db_session, invoice, None, False)
    assert "A_MISSING_FIELD" in codes


async def test_a_missing_field_invoice_number(db_session):
    invoice = await _make_invoice(db_session, invoice_number=None)
    _add_line(db_session, invoice)
    await db_session.flush()
    await db_session.refresh(invoice, attribute_names=["lines"])
    codes = await compute_anomalies(db_session, invoice, "Fournisseur", False)
    assert "A_MISSING_FIELD" in codes


async def test_a_missing_field_date(db_session):
    invoice = await _make_invoice(db_session, invoice_date=None)
    _add_line(db_session, invoice)
    await db_session.flush()
    await db_session.refresh(invoice, attribute_names=["lines"])
    codes = await compute_anomalies(db_session, invoice, "Fournisseur", False)
    assert "A_MISSING_FIELD" in codes


async def test_a_missing_field_total_ht(db_session):
    invoice = await _make_invoice(db_session, total_ht=None)
    _add_line(db_session, invoice)
    await db_session.flush()
    await db_session.refresh(invoice, attribute_names=["lines"])
    codes = await compute_anomalies(db_session, invoice, "Fournisseur", False)
    assert "A_MISSING_FIELD" in codes


async def test_a_bad_line_missing_quantity(db_session):
    invoice = await _make_invoice(db_session)
    _add_line(db_session, invoice, quantity=None)
    await db_session.flush()
    await db_session.refresh(invoice, attribute_names=["lines"])
    codes = await compute_anomalies(db_session, invoice, "Fournisseur", False)
    assert "A_BAD_LINE" in codes


async def test_a_bad_line_missing_unit_price(db_session):
    invoice = await _make_invoice(db_session)
    _add_line(db_session, invoice, unit_price_net=None)
    await db_session.flush()
    await db_session.refresh(invoice, attribute_names=["lines"])
    codes = await compute_anomalies(db_session, invoice, "Fournisseur", False)
    assert "A_BAD_LINE" in codes


async def test_a_unmapped_ref_present_then_absent_after_mapping(db_session):
    supplier = await get_or_create_supplier(db_session, "Fournisseur Anomalie SAS")
    invoice = await _make_invoice(db_session, supplier_id=supplier.id)
    _add_line(db_session, invoice)
    await db_session.flush()
    await db_session.refresh(invoice, attribute_names=["lines"])

    codes = await compute_anomalies(db_session, invoice, "Fournisseur Anomalie SAS", False)
    assert "A_UNMAPPED_REF" in codes

    from app.models.mapping import Mapping

    db_session.add(
        Mapping(
            supplier_id=supplier.id,
            supplier_ref="REF-ANOM-1",
            our_ref="INT-1",
            our_label="Interne",
            active=True,
            created_at=now_iso(),
            updated_at=now_iso(),
        )
    )
    await db_session.flush()

    codes2 = await compute_anomalies(db_session, invoice, "Fournisseur Anomalie SAS", False)
    assert "A_UNMAPPED_REF" not in codes2


async def test_a_totals_inconsistent(db_session):
    invoice = await _make_invoice(db_session, total_ht=100.0, total_vat=20.0, total_ttc=999.0)
    _add_line(db_session, invoice, line_total_net=100.0)
    await db_session.flush()
    await db_session.refresh(invoice, attribute_names=["lines"])
    codes = await compute_anomalies(db_session, invoice, "Fournisseur", False)
    assert "A_TOTALS_INCONSISTENT" in codes


async def test_a_low_confidence(db_session):
    invoice = await _make_invoice(db_session)
    _add_line(db_session, invoice, raw=json.dumps({"low_confidence": True}))
    await db_session.flush()
    await db_session.refresh(invoice, attribute_names=["lines"])
    codes = await compute_anomalies(db_session, invoice, "Fournisseur", False)
    assert "A_LOW_CONFIDENCE" in codes


async def test_a_possible_duplicate(db_session):
    supplier = await get_or_create_supplier(db_session, "Fournisseur Duplicat SAS")
    inv1 = await _make_invoice(
        db_session,
        supplier_id=supplier.id,
        invoice_number="DUP-A",
        invoice_date="2026-06-10",
        total_ttc=120.0,
        file_hash="h1",
    )
    _add_line(db_session, inv1)
    await db_session.flush()

    inv2 = await _make_invoice(
        db_session,
        supplier_id=supplier.id,
        invoice_number="DUP-B",
        invoice_date="2026-06-10",
        total_ttc=120.0,
        file_hash="h2",
    )
    _add_line(db_session, inv2)
    await db_session.flush()
    await db_session.refresh(inv2, attribute_names=["lines"])

    codes = await compute_anomalies(db_session, inv2, "Fournisseur Duplicat SAS", False)
    assert "A_POSSIBLE_DUPLICATE" in codes


async def test_a_new_supplier_is_non_blocking(db_session):
    invoice = await _make_invoice(db_session)
    _add_line(db_session, invoice)
    await db_session.flush()
    await db_session.refresh(invoice, attribute_names=["lines"])

    from app.models.mapping import Mapping

    db_session.add(
        Mapping(
            supplier_id=None,
            supplier_ref="REF-ANOM-1",
            our_ref="INT-1",
            our_label="Interne",
            active=True,
            created_at=now_iso(),
            updated_at=now_iso(),
        )
    )
    await db_session.flush()

    codes = await compute_anomalies(db_session, invoice, "Nouveau Fournisseur", True)
    assert codes == ["A_NEW_SUPPLIER"]
    assert status_from_anomalies(codes) == "VALIDATED"
