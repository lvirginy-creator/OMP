"""Génère des PDF synthétiques pour les tests (§11 du cahier des charges) —
aucun document réel n'est nécessaire pour faire tourner la suite."""

import io
import random

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import pypdfium2 as pdfium
from PIL import Image


def _draw_simple_invoice(c: canvas.Canvas):
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, 800, "FOURNISSEUR TEST SAS")
    c.setFont("Helvetica", 10)
    c.drawString(50, 780, "Facture n° F2026-001")
    c.drawString(50, 765, "Date : 15/01/2026")

    c.drawString(50, 720, "Référence")
    c.drawString(200, 720, "Désignation")
    c.drawString(400, 720, "Qté")
    c.drawString(440, 720, "PU HT")
    c.drawString(500, 720, "Total HT")

    c.drawString(50, 700, "ABC-100")
    c.drawString(200, 700, "Article de test A")
    c.drawString(400, 700, "10")
    c.drawString(440, 700, "5,00")
    c.drawString(500, 700, "50,00")

    c.drawString(50, 685, "ABC-200")
    c.drawString(200, 685, "Article de test B")
    c.drawString(400, 685, "2")
    c.drawString(440, 685, "25,00")
    c.drawString(500, 685, "50,00")

    c.drawString(400, 650, "Total HT : 100,00 €")
    c.drawString(400, 635, "TVA (20%) : 20,00 €")
    c.drawString(400, 620, "Total TTC : 120,00 €")


def simple_invoice_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _draw_simple_invoice(c)
    c.showPage()
    c.save()
    return buf.getvalue()


def invoice_with_discount_shipping_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, 800, "FOURNISSEUR TEST SAS")
    c.setFont("Helvetica", 10)
    c.drawString(50, 780, "Facture n° F2026-002")
    c.drawString(50, 765, "Date : 20/01/2026")

    c.drawString(50, 700, "ABC-100  Article de test A   10   5,00   50,00")
    c.drawString(50, 685, "Frais de port                1    8,00    8,00")
    c.drawString(50, 670, "Remise commerciale                       -5,00")

    c.drawString(400, 630, "Total HT : 53,00 €")
    c.drawString(400, 615, "TVA (20%) : 10,60 €")
    c.drawString(400, 600, "Total TTC : 63,60 €")
    c.showPage()
    c.save()
    return buf.getvalue()


def credit_note_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, 800, "FOURNISSEUR TEST SAS")
    c.setFont("Helvetica", 10)
    c.drawString(50, 780, "AVOIR n° A2026-001")
    c.drawString(50, 765, "Date : 25/01/2026")
    c.drawString(50, 700, "ABC-100  Retour article A   1   5,00   5,00")
    c.drawString(400, 650, "Total HT : 5,00 €")
    c.drawString(400, 635, "TVA (20%) : 1,00 €")
    c.drawString(400, 620, "Total TTC : 6,00 €")
    c.showPage()
    c.save()
    return buf.getvalue()


def _render_first_page_to_image(pdf_bytes: bytes) -> Image.Image:
    pdf = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    try:
        page = pdf[0]
        bitmap = page.render(scale=200 / 72)
        return bitmap.to_pil().convert("RGB")
    finally:
        pdf.close()


def scanned_simple_invoice_pdf() -> bytes:
    """Image pleine page, sans aucune couche texte — simule un scan."""
    image = _render_first_page_to_image(simple_invoice_pdf())
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawImage(ImageReader(image), 0, 0, width=A4[0], height=A4[1])
    c.showPage()
    c.save()
    return buf.getvalue()


def scanned_noisy_ocr_invoice_pdf() -> bytes:
    """Image pleine page + couche texte OCR volontairement dégradée (peu de lettres,
    beaucoup de caractères isolés, aucun motif de montant reconnaissable)."""
    image = _render_first_page_to_image(simple_invoice_pdf())
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawImage(ImageReader(image), 0, 0, width=A4[0], height=A4[1])

    rng = random.Random(42)
    noisy_chars = "|_~^`°§#{}[]<>*"
    c.setFont("Helvetica", 8)
    c.setFillAlpha(0.0)  # texte invisible superposé, comme une couche OCR ratée
    y = 780
    for _ in range(200):
        token = "".join(rng.choice(noisy_chars) for _ in range(rng.randint(2, 4)))
        c.drawString(rng.randint(50, 500), y, token)
        y -= 12
        if y < 50:
            y = 780

    c.showPage()
    c.save()
    return buf.getvalue()


def mixte_pdf() -> bytes:
    """Page 1 native propre + page 2 scannée — doit être classé MIXTE."""
    scan_image = _render_first_page_to_image(simple_invoice_pdf())

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _draw_simple_invoice(c)
    c.showPage()
    c.drawImage(ImageReader(scan_image), 0, 0, width=A4[0], height=A4[1])
    c.showPage()
    c.save()
    return buf.getvalue()
