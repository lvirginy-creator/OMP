import json

from app.models.invoice import Invoice
from app.services import invoice_pipeline
from app.services.mapping_queue import create_mapping_and_recompute, get_unmapped_groups
from tests.fixtures.pdf_builder import simple_invoice_pdf


def _result(**overrides):
    result = {
        "document_type": "INVOICE",
        "supplier_name": "Fournisseur Queue SAS",
        "invoice_number": "F-Q-1",
        "invoice_date": "2026-03-01",
        "currency": "EUR",
        "total_ht": 70.0,
        "total_vat": 14.0,
        "total_ttc": 84.0,
        "lines": [
            {
                "line_type": "ARTICLE",
                "charge_kind": None,
                "supplier_ref": "QREF-1",
                "supplier_label": "Article file d'attente",
                "quantity": 7.0,
                "unit_price_net": 10.0,
                "line_total_net": 70.0,
                "vat_rate": 20.0,
                "low_confidence": False,
            },
        ],
        "page_count_documents": 1,
    }
    result.update(overrides)
    return result


async def test_unmapped_group_appears_with_cumulative_quantity(db_session, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from app.core.config import get_settings

    get_settings.cache_clear()

    async def fake_extract_text_mode(text_payload):
        return _result()

    monkeypatch.setattr(invoice_pipeline, "extract_text_mode", fake_extract_text_mode)

    r1 = await invoice_pipeline.process_uploaded_pdf(db_session, "a.pdf", simple_invoice_pdf())
    assert r1.outcome == "CREATED"

    async def fake_extract_text_mode_2(text_payload):
        return _result(invoice_number="F-Q-2", invoice_date="2026-03-05")

    monkeypatch.setattr(invoice_pipeline, "extract_text_mode", fake_extract_text_mode_2)
    r2 = await invoice_pipeline.process_uploaded_pdf(
        db_session, "b.pdf", simple_invoice_pdf() + b"\n%pad"
    )
    assert r2.outcome == "CREATED"

    groups = await get_unmapped_groups(db_session)
    matching = [g for g in groups if g.supplier_ref_norm == "QREF1"]
    assert len(matching) == 1
    group = matching[0]
    assert group.line_count == 2
    assert group.total_qty == 14.0
    assert group.first_date == "2026-03-01"
    assert group.last_date == "2026-03-05"

    get_settings.cache_clear()


async def test_create_mapping_retroactively_validates_invoice(db_session, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from app.core.config import get_settings

    get_settings.cache_clear()

    async def fake_extract_text_mode(text_payload):
        return _result()

    monkeypatch.setattr(invoice_pipeline, "extract_text_mode", fake_extract_text_mode)

    result = await invoice_pipeline.process_uploaded_pdf(db_session, "a.pdf", simple_invoice_pdf())
    invoice = await db_session.get(Invoice, result.invoice_id)
    codes_before = json.loads(invoice.anomalies)
    assert "A_UNMAPPED_REF" in codes_before
    assert invoice.status == "NEEDS_REVIEW"

    groups = await get_unmapped_groups(db_session)
    group = next(g for g in groups if g.supplier_ref_norm == "QREF1")

    await create_mapping_and_recompute(
        db_session, group.supplier_id, group.supplier_ref, "INT-QREF1", "Article interne", ""
    )

    await db_session.refresh(invoice)
    codes_after = json.loads(invoice.anomalies)
    assert "A_UNMAPPED_REF" not in codes_after
    assert invoice.status == "VALIDATED"
    assert invoice.validated_at is not None

    groups_after = await get_unmapped_groups(db_session)
    assert not any(g.supplier_ref_norm == "QREF1" for g in groups_after)

    get_settings.cache_clear()
