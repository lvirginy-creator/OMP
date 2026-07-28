import json

import pytest
from sqlalchemy import select

from app.models.invoice import Invoice
from app.models.mapping import Mapping
from app.services import invoice_pipeline
from app.services.suppliers import now_iso
from tests.fixtures.pdf_builder import scanned_simple_invoice_pdf, simple_invoice_pdf


def _clean_result(**overrides):
    result = {
        "document_type": "INVOICE",
        "supplier_name": "Fournisseur Test SAS",
        "invoice_number": "F2026-001",
        "invoice_date": "2026-01-15",
        "currency": "EUR",
        "total_ht": 100.0,
        "total_vat": 20.0,
        "total_ttc": 120.0,
        "lines": [
            {
                "line_type": "ARTICLE",
                "charge_kind": None,
                "supplier_ref": "ABC-100",
                "supplier_label": "Article de test A",
                "quantity": 10.0,
                "unit_price_net": 5.0,
                "line_total_net": 50.0,
                "vat_rate": 20.0,
                "low_confidence": False,
            },
            {
                "line_type": "ARTICLE",
                "charge_kind": None,
                "supplier_ref": "ABC-200",
                "supplier_label": "Article de test B",
                "quantity": 2.0,
                "unit_price_net": 25.0,
                "line_total_net": 50.0,
                "vat_rate": 20.0,
                "low_confidence": False,
            },
        ],
        "page_count_documents": 1,
    }
    result.update(overrides)
    return result


@pytest.fixture(autouse=True)
def anthropic_key_enabled(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_duplicate_file_hash_is_rejected(db_session, monkeypatch):
    call_count = {"n": 0}

    async def fake_extract_text_mode(text_payload):
        call_count["n"] += 1
        return _clean_result()

    monkeypatch.setattr(invoice_pipeline, "extract_text_mode", fake_extract_text_mode)

    content = simple_invoice_pdf()
    r1 = await invoice_pipeline.process_uploaded_pdf(db_session, "f1.pdf", content)
    assert r1.outcome == "CREATED"

    r2 = await invoice_pipeline.process_uploaded_pdf(db_session, "f1_copie.pdf", content)
    assert r2.outcome == "REJECTED_DUPLICATE"
    assert r2.existing_invoice_id == r1.invoice_id
    assert call_count["n"] == 1  # le doublon ne doit pas déclencher un second appel LLM


async def test_duplicate_business_key_is_rejected(db_session, monkeypatch):
    async def fake_extract_text_mode(text_payload):
        return _clean_result()

    monkeypatch.setattr(invoice_pipeline, "extract_text_mode", fake_extract_text_mode)

    r1 = await invoice_pipeline.process_uploaded_pdf(db_session, "a.pdf", simple_invoice_pdf())
    assert r1.outcome == "CREATED"

    # Fichier différent (contenu modifié -> hash différent) mais même triplet métier
    other_content = simple_invoice_pdf() + b"\n%padding"
    r2 = await invoice_pipeline.process_uploaded_pdf(db_session, "b.pdf", other_content)
    assert r2.outcome == "REJECTED_DUPLICATE"
    assert r2.existing_invoice_id == r1.invoice_id


async def test_credit_note_signs_are_forced_negative(db_session, monkeypatch):
    async def fake_extract_text_mode(text_payload):
        return _clean_result(
            document_type="CREDIT_NOTE",
            total_ht=5.0,
            total_vat=1.0,
            total_ttc=6.0,
            lines=[
                {
                    "line_type": "ARTICLE",
                    "charge_kind": None,
                    "supplier_ref": "ABC-100",
                    "supplier_label": "Retour article A",
                    "quantity": 1.0,
                    "unit_price_net": 5.0,
                    "line_total_net": 5.0,
                    "vat_rate": 20.0,
                    "low_confidence": False,
                }
            ],
        )

    monkeypatch.setattr(invoice_pipeline, "extract_text_mode", fake_extract_text_mode)

    result = await invoice_pipeline.process_uploaded_pdf(db_session, "avoir.pdf", simple_invoice_pdf())
    assert result.outcome == "CREATED"

    invoice = await db_session.get(Invoice, result.invoice_id)
    await db_session.refresh(invoice, attribute_names=["lines"])
    assert invoice.total_ht == -5.0
    assert invoice.total_ttc == -6.0
    assert invoice.lines[0].quantity == -1.0
    assert invoice.lines[0].line_total_net == -5.0


async def test_unreliable_text_result_escalates_to_vision_max_two_calls(db_session, monkeypatch):
    calls = {"text": 0, "vision": 0}

    async def fake_extract_text_mode(text_payload):
        calls["text"] += 1
        return _clean_result(lines=[])  # aucune ligne -> non fiable

    async def fake_extract_vision_mode(images):
        calls["vision"] += 1
        return _clean_result()

    monkeypatch.setattr(invoice_pipeline, "extract_text_mode", fake_extract_text_mode)
    monkeypatch.setattr(invoice_pipeline, "extract_vision_mode", fake_extract_vision_mode)

    result = await invoice_pipeline.process_uploaded_pdf(db_session, "f.pdf", simple_invoice_pdf())
    assert result.outcome == "CREATED"

    invoice = await db_session.get(Invoice, result.invoice_id)
    assert invoice.extraction_method == "NATIVE_THEN_VISION"
    assert calls == {"text": 1, "vision": 1}


async def test_scanned_pdf_uses_vision_mode_directly(db_session, monkeypatch):
    calls = {"text": 0, "vision": 0}

    async def fake_extract_text_mode(text_payload):
        calls["text"] += 1
        return _clean_result()

    async def fake_extract_vision_mode(images):
        calls["vision"] += 1
        return _clean_result()

    monkeypatch.setattr(invoice_pipeline, "extract_text_mode", fake_extract_text_mode)
    monkeypatch.setattr(invoice_pipeline, "extract_vision_mode", fake_extract_vision_mode)

    result = await invoice_pipeline.process_uploaded_pdf(
        db_session, "scan.pdf", scanned_simple_invoice_pdf()
    )
    assert result.outcome == "CREATED"
    invoice = await db_session.get(Invoice, result.invoice_id)
    assert invoice.extraction_method == "VISION_LLM"
    assert invoice.doc_class == "SCAN"
    assert calls == {"text": 0, "vision": 1}


async def test_multi_invoice_pdf_is_rejected_without_saving(db_session, monkeypatch):
    async def fake_extract_text_mode(text_payload):
        return _clean_result(page_count_documents=3)

    monkeypatch.setattr(invoice_pipeline, "extract_text_mode", fake_extract_text_mode)

    result = await invoice_pipeline.process_uploaded_pdf(db_session, "multi.pdf", simple_invoice_pdf())
    assert result.outcome == "ERROR"

    count = (await db_session.execute(select(Invoice))).scalars().all()
    assert count == []


async def test_unmapped_article_ref_triggers_needs_review_then_validated_after_mapping(
    db_session, monkeypatch
):
    async def fake_extract_text_mode(text_payload):
        return _clean_result()

    monkeypatch.setattr(invoice_pipeline, "extract_text_mode", fake_extract_text_mode)

    result = await invoice_pipeline.process_uploaded_pdf(db_session, "f.pdf", simple_invoice_pdf())
    invoice = await db_session.get(Invoice, result.invoice_id)
    anomalies = json.loads(invoice.anomalies)
    assert "A_UNMAPPED_REF" in anomalies
    assert invoice.status == "NEEDS_REVIEW"

    timestamp = now_iso()
    db_session.add(
        Mapping(
            supplier_id=None,
            supplier_ref="ABC-100",
            our_ref="INT-ABC100",
            our_label="Article A interne",
            active=True,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    db_session.add(
        Mapping(
            supplier_id=None,
            supplier_ref="ABC-200",
            our_ref="INT-ABC200",
            our_label="Article B interne",
            active=True,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    await db_session.commit()

    from app.services.anomalies import compute_anomalies, status_from_anomalies

    await db_session.refresh(invoice, attribute_names=["lines"])
    codes = await compute_anomalies(db_session, invoice, "Fournisseur Test SAS", False)
    assert "A_UNMAPPED_REF" not in codes
    assert status_from_anomalies(codes) == "VALIDATED"
