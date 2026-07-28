import pdfplumber


def build_text_payload(pdf_path: str) -> str:
    """MODE A : texte brut + tables détectées, page par page, dans l'ordre de lecture."""
    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            parts.append(f"--- Page {idx} ---")
            text = page.extract_text() or ""
            if text:
                parts.append(text)
            for table in page.extract_tables():
                for row in table:
                    cells = ["" if c is None else str(c).replace("\n", " ") for c in row]
                    parts.append("\t".join(cells))
    return "\n".join(parts)
