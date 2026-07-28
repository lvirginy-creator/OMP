import base64
import io

import pypdfium2 as pdfium

RENDER_DPI = 200
MAX_DIMENSION_PX = 1800


def render_pages_as_png_base64(pdf_path: str) -> list[str]:
    """MODE B : rendu de chaque page en PNG niveaux de gris, redimensionné, en base64."""
    images_b64: list[str] = []
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        for page in pdf:
            bitmap = page.render(scale=RENDER_DPI / 72)
            pil_image = bitmap.to_pil().convert("L")

            max_side = max(pil_image.width, pil_image.height)
            if max_side > MAX_DIMENSION_PX:
                ratio = MAX_DIMENSION_PX / max_side
                new_size = (round(pil_image.width * ratio), round(pil_image.height * ratio))
                pil_image = pil_image.resize(new_size)

            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            images_b64.append(base64.b64encode(buf.getvalue()).decode("ascii"))
            page.close()
    finally:
        pdf.close()

    return images_b64


def count_pages(pdf_path: str) -> int:
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        return len(pdf)
    finally:
        pdf.close()
