import re
from dataclasses import dataclass, field

import pdfplumber

_ALLOWED_CHARS_RE = re.compile(r"[A-Za-z0-9À-ÿ ,.\-/€%]")
_AMOUNT_RE = re.compile(r"\d+[ .,]\d{2}")

TEXT_DENSITY_MIN_CHARS = 150
IMAGE_COVERAGE_MAX_RATIO = 0.80
ALPHANUM_RATIO_MIN = 0.85
SHORT_WORD_RATIO_MAX = 0.30


@dataclass
class PageDiagnostics:
    page_number: int
    char_count: int
    image_coverage_ratio: float
    alphanum_ratio: float
    amount_matches: int
    short_word_ratio: float
    suspect: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class DocumentDiagnostics:
    doc_class: str  # TEXTE | SCAN | MIXTE
    pages: list[PageDiagnostics]
    page_count: int


def _page_diagnostics(page: "pdfplumber.page.Page", page_number: int) -> PageDiagnostics:
    text = page.extract_text() or ""
    char_count = len(text)

    page_area = float(page.width) * float(page.height) if page.width and page.height else 0.0
    image_area = 0.0
    for img in page.images:
        w = max(0.0, float(img.get("x1", 0)) - float(img.get("x0", 0)))
        h = max(0.0, float(img.get("y1", 0)) - float(img.get("y0", 0)))
        image_area += w * h
    image_coverage_ratio = (image_area / page_area) if page_area > 0 else 0.0

    if text:
        allowed = sum(1 for c in text if _ALLOWED_CHARS_RE.match(c))
        alphanum_ratio = allowed / len(text)
    else:
        alphanum_ratio = 0.0

    amount_matches = len(_AMOUNT_RE.findall(text))

    words = text.split()
    short_word_ratio = (
        sum(1 for w in words if len(w) == 1) / len(words) if words else 0.0
    )

    reasons = []
    if char_count < TEXT_DENSITY_MIN_CHARS:
        reasons.append("densite_texte_faible")
    if image_coverage_ratio > IMAGE_COVERAGE_MAX_RATIO:
        reasons.append("couverture_image_forte")
    if alphanum_ratio < ALPHANUM_RATIO_MIN:
        reasons.append("ratio_alphanumerique_faible")
    if amount_matches == 0:
        reasons.append("aucun_montant_detecte")
    if short_word_ratio > SHORT_WORD_RATIO_MAX:
        reasons.append("mots_courts_isoles")

    return PageDiagnostics(
        page_number=page_number,
        char_count=char_count,
        image_coverage_ratio=round(image_coverage_ratio, 3),
        alphanum_ratio=round(alphanum_ratio, 3),
        amount_matches=amount_matches,
        short_word_ratio=round(short_word_ratio, 3),
        suspect=bool(reasons),
        reasons=reasons,
    )


def classify_pdf(pdf_path: str) -> DocumentDiagnostics:
    pages: list[PageDiagnostics] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            pages.append(_page_diagnostics(page, idx))

    if not pages:
        return DocumentDiagnostics(doc_class="SCAN", pages=pages, page_count=0)

    suspects = [p.suspect for p in pages]
    if all(not s for s in suspects):
        doc_class = "TEXTE"
    elif all(s for s in suspects):
        doc_class = "SCAN"
    else:
        doc_class = "MIXTE"

    return DocumentDiagnostics(doc_class=doc_class, pages=pages, page_count=len(pages))
