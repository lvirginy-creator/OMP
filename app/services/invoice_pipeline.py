import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.import_log import ImportLog
from app.models.invoice import Invoice, InvoiceLine
from app.models.supplier import Supplier
from app.services.anomalies import compute_anomalies, status_from_anomalies
from app.services.claude_extraction import (
    UnreliableExtractionError,
    extract_text_mode,
    extract_vision_mode,
    is_result_unreliable,
    pick_best_result,
)
from app.services.normalize import normalize_supplier_name
from app.services.pdf_classify import classify_pdf
from app.services.pdf_extract_text import build_text_payload
from app.services.pdf_render import count_pages, render_pages_as_png_base64
from app.services.suppliers import get_or_create_supplier, now_iso

MAX_VISION_PAGES = 12


@dataclass
class ProcessResult:
    outcome: str  # "CREATED" | "REJECTED_DUPLICATE" | "ERROR"
    invoice_id: int | None = None
    message: str | None = None
    existing_invoice_id: int | None = None


def _round2(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _apply_sign_rules(result: dict) -> None:
    negate = result.get("document_type") == "CREDIT_NOTE"

    def sign(v):
        if v is None:
            return None
        return -abs(v) if negate else abs(v)

    for key in ("total_ht", "total_vat", "total_ttc"):
        result[key] = sign(result.get(key))
    for line in result.get("lines") or []:
        line["quantity"] = sign(line.get("quantity"))
        line["line_total_net"] = sign(line.get("line_total_net"))


def _recompute_line_amounts(result: dict) -> None:
    for line in result.get("lines") or []:
        qty = line.get("quantity")
        unit = line.get("unit_price_net")
        total = line.get("line_total_net")
        if total is None and qty is not None and unit is not None:
            line["line_total_net"] = _round2(qty * unit)
        elif unit is None and total is not None and qty:
            line["unit_price_net"] = _round2(total / qty)


async def _run_extraction(
    content: bytes, doc_class: str, tolerance: float
) -> tuple[dict, str]:
    """Retourne (résultat, extraction_method)."""
    if doc_class == "TEXTE":
        text_payload = build_text_payload(io.BytesIO(content))
        result_a = await extract_text_mode(text_payload)
        if not is_result_unreliable(result_a, tolerance):
            return result_a, "NATIVE_LLM"
        images = render_pages_as_png_base64(io.BytesIO(content))
        result_b = await extract_vision_mode(images)
        best, method = pick_best_result(result_a, result_b, tolerance)
        return best, method

    images = render_pages_as_png_base64(io.BytesIO(content))
    result_b = await extract_vision_mode(images)
    return result_b, "VISION_LLM"


def _empty_manual_result() -> dict:
    return {
        "document_type": "INVOICE",
        "supplier_name": None,
        "invoice_number": None,
        "invoice_date": None,
        "currency": "EUR",
        "total_ht": None,
        "total_vat": None,
        "total_ttc": None,
        "lines": [],
        "page_count_documents": 1,
    }


async def process_uploaded_pdf(
    db: AsyncSession, filename: str, content: bytes
) -> ProcessResult:
    settings = get_settings()
    file_hash = hashlib.sha256(content).hexdigest()
    timestamp = now_iso()

    existing = (
        await db.execute(select(Invoice).where(Invoice.file_hash == file_hash))
    ).scalar_one_or_none()
    if existing is not None:
        db.add(
            ImportLog(
                kind="INVOICE",
                filename=filename,
                file_hash=file_hash,
                invoice_id=existing.id,
                outcome="REJECTED_DUPLICATE",
                message="Fichier identique déjà importé",
                created_at=timestamp,
            )
        )
        await db.commit()
        return ProcessResult(
            outcome="REJECTED_DUPLICATE",
            message="Ce fichier a déjà été importé.",
            existing_invoice_id=existing.id,
        )

    diag = classify_pdf(io.BytesIO(content))
    page_count = diag.page_count or count_pages(io.BytesIO(content))

    too_many_pages = page_count > MAX_VISION_PAGES and diag.doc_class in ("SCAN", "MIXTE")
    no_api_key = not settings.anthropic_api_key

    result: dict | None = None
    extraction_method = "MANUAL"
    error_message = None

    if not too_many_pages and not no_api_key:
        try:
            result, extraction_method = await _run_extraction(
                content, diag.doc_class, settings.tolerance_total
            )
        except UnreliableExtractionError as exc:
            error_message = str(exc)
        except Exception as exc:  # erreurs API (réseau, clé invalide, rate limit...)
            error_message = f"Échec de l'extraction automatique : {exc}"

    if result is not None and (result.get("page_count_documents") or 1) > 1:
        message = (
            f"Ce PDF semble contenir {result.get('page_count_documents')} factures "
            "distinctes — merci de le découper et de redéposer les fichiers séparément."
        )
        db.add(
            ImportLog(
                kind="INVOICE",
                filename=filename,
                file_hash=file_hash,
                outcome="ERROR",
                message=message,
                created_at=timestamp,
            )
        )
        await db.commit()
        return ProcessResult(outcome="ERROR", message=message)

    if result is None:
        result = _empty_manual_result()

    _recompute_line_amounts(result)
    _apply_sign_rules(result)

    supplier: Supplier | None = None
    is_new_supplier = False
    supplier_name_raw = (result.get("supplier_name") or "").strip() or None
    if supplier_name_raw:
        normalized = normalize_supplier_name(supplier_name_raw)
        existing_supplier = (
            await db.execute(select(Supplier).where(Supplier.normalized_name == normalized))
        ).scalar_one_or_none()
        is_new_supplier = existing_supplier is None
        supplier = await get_or_create_supplier(db, supplier_name_raw)

    supplier_id = supplier.id if supplier else None
    invoice_number = result.get("invoice_number")
    document_type = result.get("document_type") or "INVOICE"

    invoice = Invoice(
        supplier_id=supplier_id,
        document_type=document_type,
        invoice_number=invoice_number,
        invoice_date=result.get("invoice_date"),
        currency=result.get("currency") or "EUR",
        total_ht=result.get("total_ht"),
        total_vat=result.get("total_vat"),
        total_ttc=result.get("total_ttc"),
        status="NEEDS_REVIEW",
        extraction_method=extraction_method,
        doc_class=diag.doc_class,
        raw_diagnostics=json.dumps(
            {
                "pages": [
                    {
                        "page_number": p.page_number,
                        "char_count": p.char_count,
                        "image_coverage_ratio": p.image_coverage_ratio,
                        "alphanum_ratio": p.alphanum_ratio,
                        "amount_matches": p.amount_matches,
                        "short_word_ratio": p.short_word_ratio,
                        "suspect": p.suspect,
                        "reasons": p.reasons,
                    }
                    for p in diag.pages
                ],
                "error": error_message,
            },
            ensure_ascii=False,
        ),
        source_filename=filename,
        file_hash=file_hash,
        stored_path="",
        anomalies=None,
        notes=None,
        created_at=timestamp,
    )
    db.add(invoice)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        conflict = (
            await db.execute(
                select(Invoice).where(
                    Invoice.supplier_id == supplier_id,
                    Invoice.invoice_number == invoice_number,
                    Invoice.document_type == document_type,
                )
            )
        ).scalar_one_or_none()
        db.add(
            ImportLog(
                kind="INVOICE",
                filename=filename,
                file_hash=file_hash,
                invoice_id=conflict.id if conflict else None,
                outcome="REJECTED_DUPLICATE",
                message=f"Facture n° {invoice_number} déjà importée pour ce fournisseur",
                created_at=timestamp,
            )
        )
        await db.commit()
        return ProcessResult(
            outcome="REJECTED_DUPLICATE",
            message=f"Cette facture n° {invoice_number} a déjà été importée.",
            existing_invoice_id=conflict.id if conflict else None,
        )

    for idx, line in enumerate(result.get("lines") or [], start=1):
        db.add(
            InvoiceLine(
                invoice_id=invoice.id,
                line_no=idx,
                line_type=line.get("line_type") or "ARTICLE",
                charge_kind=line.get("charge_kind"),
                supplier_ref=line.get("supplier_ref"),
                supplier_label=line.get("supplier_label"),
                quantity=line.get("quantity"),
                unit_price_net=line.get("unit_price_net"),
                line_total_net=line.get("line_total_net"),
                vat_rate=line.get("vat_rate"),
                raw=json.dumps(line, ensure_ascii=False),
            )
        )
    await db.flush()
    await db.refresh(invoice, attribute_names=["lines"])

    pdf_dir = settings.pdfs_path
    pdf_dir.mkdir(parents=True, exist_ok=True)
    stored_path = pdf_dir / f"{invoice.id}.pdf"
    stored_path.write_bytes(content)
    invoice.stored_path = str(stored_path)

    codes = ["A_TOO_MANY_PAGES"] if too_many_pages else []
    codes += await compute_anomalies(db, invoice, supplier_name_raw, is_new_supplier)
    if error_message and "A_NO_LINES" not in codes:
        codes.append("A_NO_LINES")
    codes = list(dict.fromkeys(codes))  # dédoublonne en conservant l'ordre

    invoice.anomalies = json.dumps(codes)
    invoice.status = status_from_anomalies(codes)
    if invoice.status == "VALIDATED":
        invoice.validated_at = timestamp

    db.add(
        ImportLog(
            kind="INVOICE",
            filename=filename,
            file_hash=file_hash,
            invoice_id=invoice.id,
            outcome="CREATED",
            message=f"Statut : {invoice.status}",
            created_at=timestamp,
        )
    )
    await db.commit()

    return ProcessResult(outcome="CREATED", invoice_id=invoice.id)


@dataclass
class ReextractResult:
    ok: bool
    message: str | None = None


async def reextract_invoice(
    db: AsyncSession, invoice: Invoice, force_vision: bool = False
) -> ReextractResult:
    """Rejoue le pipeline sur le PDF déjà stocké (§5.1.e). Remplace les lignes, conserve l'id."""
    settings = get_settings()
    content = Path(invoice.stored_path).read_bytes()
    timestamp = now_iso()

    diag = classify_pdf(io.BytesIO(content))
    page_count = diag.page_count or count_pages(io.BytesIO(content))
    doc_class = "SCAN" if force_vision else diag.doc_class
    too_many_pages = page_count > MAX_VISION_PAGES and doc_class in ("SCAN", "MIXTE")

    if too_many_pages:
        return ReextractResult(ok=False, message="Ce document dépasse 12 pages en mode scan.")
    if not settings.anthropic_api_key:
        return ReextractResult(ok=False, message="Aucune clé ANTHROPIC_API_KEY configurée.")

    error_message = None
    try:
        if force_vision:
            images = render_pages_as_png_base64(io.BytesIO(content))
            result = await extract_vision_mode(images)
            extraction_method = "VISION_LLM"
        else:
            result, extraction_method = await _run_extraction(
                content, diag.doc_class, settings.tolerance_total
            )
    except UnreliableExtractionError as exc:
        return ReextractResult(ok=False, message=str(exc))
    except Exception as exc:
        return ReextractResult(ok=False, message=f"Échec de l'extraction : {exc}")

    if (result.get("page_count_documents") or 1) > 1:
        return ReextractResult(
            ok=False,
            message=(
                f"Ce PDF semble contenir {result.get('page_count_documents')} factures "
                "distinctes — ré-extraction annulée."
            ),
        )

    _recompute_line_amounts(result)
    _apply_sign_rules(result)

    supplier: Supplier | None = None
    is_new_supplier = False
    supplier_name_raw = (result.get("supplier_name") or "").strip() or None
    if supplier_name_raw:
        normalized = normalize_supplier_name(supplier_name_raw)
        existing_supplier = (
            await db.execute(select(Supplier).where(Supplier.normalized_name == normalized))
        ).scalar_one_or_none()
        is_new_supplier = existing_supplier is None
        supplier = await get_or_create_supplier(db, supplier_name_raw)

    invoice.supplier_id = supplier.id if supplier else None
    invoice.document_type = result.get("document_type") or "INVOICE"
    invoice.invoice_number = result.get("invoice_number")
    invoice.invoice_date = result.get("invoice_date")
    invoice.currency = result.get("currency") or "EUR"
    invoice.total_ht = result.get("total_ht")
    invoice.total_vat = result.get("total_vat")
    invoice.total_ttc = result.get("total_ttc")
    invoice.extraction_method = extraction_method
    invoice.doc_class = diag.doc_class
    invoice.raw_diagnostics = json.dumps(
        {
            "pages": [
                {
                    "page_number": p.page_number,
                    "char_count": p.char_count,
                    "image_coverage_ratio": p.image_coverage_ratio,
                    "alphanum_ratio": p.alphanum_ratio,
                    "amount_matches": p.amount_matches,
                    "short_word_ratio": p.short_word_ratio,
                    "suspect": p.suspect,
                    "reasons": p.reasons,
                }
                for p in diag.pages
            ],
            "error": error_message,
            "reextracted_at": timestamp,
        },
        ensure_ascii=False,
    )

    for line in list(invoice.lines):
        await db.delete(line)
    await db.flush()

    for idx, line in enumerate(result.get("lines") or [], start=1):
        db.add(
            InvoiceLine(
                invoice_id=invoice.id,
                line_no=idx,
                line_type=line.get("line_type") or "ARTICLE",
                charge_kind=line.get("charge_kind"),
                supplier_ref=line.get("supplier_ref"),
                supplier_label=line.get("supplier_label"),
                quantity=line.get("quantity"),
                unit_price_net=line.get("unit_price_net"),
                line_total_net=line.get("line_total_net"),
                vat_rate=line.get("vat_rate"),
                raw=json.dumps(line, ensure_ascii=False),
            )
        )
    await db.flush()
    await db.refresh(invoice, attribute_names=["lines"])

    codes = await compute_anomalies(db, invoice, supplier_name_raw, is_new_supplier)
    invoice.anomalies = json.dumps(codes)
    invoice.status = status_from_anomalies(codes)
    invoice.validated_at = timestamp if invoice.status == "VALIDATED" else None

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return ReextractResult(
            ok=False,
            message="Cette référence de facture entre en conflit avec une autre facture existante.",
        )

    return ReextractResult(ok=True)
