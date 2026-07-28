import io

from app.services.pdf_classify import classify_pdf
from tests.fixtures.pdf_builder import (
    mixte_pdf,
    scanned_noisy_ocr_invoice_pdf,
    scanned_simple_invoice_pdf,
    simple_invoice_pdf,
)


def test_native_clean_pdf_is_classified_texte():
    diag = classify_pdf(io.BytesIO(simple_invoice_pdf()))
    assert diag.doc_class == "TEXTE"
    assert diag.page_count == 1
    assert not diag.pages[0].suspect


def test_image_only_pdf_is_classified_scan():
    diag = classify_pdf(io.BytesIO(scanned_simple_invoice_pdf()))
    assert diag.doc_class == "SCAN"
    assert diag.pages[0].suspect
    assert diag.pages[0].char_count == 0


def test_degraded_ocr_layer_is_classified_scan_not_texte():
    diag = classify_pdf(io.BytesIO(scanned_noisy_ocr_invoice_pdf()))
    assert diag.doc_class == "SCAN"
    assert diag.pages[0].suspect
    # texte présent (couche OCR), mais de mauvaise qualité — pas une simple densité nulle
    assert diag.pages[0].char_count > 0
    assert "ratio_alphanumerique_faible" in diag.pages[0].reasons


def test_mixed_document_is_classified_mixte():
    diag = classify_pdf(io.BytesIO(mixte_pdf()))
    assert diag.doc_class == "MIXTE"
    assert diag.page_count == 2
    assert diag.pages[0].suspect is False
    assert diag.pages[1].suspect is True
