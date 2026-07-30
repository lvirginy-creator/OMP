import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.invoice import Invoice
from app.services.mapping_resolution import resolve_mapping

NON_BLOCKING_ANOMALIES = {"A_NEW_SUPPLIER"}
VALIDATE_BLOCKING_ANOMALIES = {"A_TOTAL_MISMATCH", "A_MISSING_FIELD"}


async def find_duplicate_candidate(db: AsyncSession, invoice: Invoice) -> Invoice | None:
    """Facture existante soupçonnée d'être un doublon de celle-ci (§6.1.b)."""
    if not (invoice.total_ttc is not None and invoice.invoice_date and invoice.supplier_id):
        return None
    stmt = select(Invoice).where(
        Invoice.id != invoice.id,
        Invoice.supplier_id == invoice.supplier_id,
        Invoice.invoice_date == invoice.invoice_date,
    )
    candidates = (await db.execute(stmt)).scalars().all()
    for other in candidates:
        if other.total_ttc is None:
            continue
        if abs(other.total_ttc - invoice.total_ttc) > 0.01:
            continue
        if other.invoice_number != invoice.invoice_number or not invoice.invoice_number:
            return other
    return None


async def compute_anomalies(
    db: AsyncSession,
    invoice: Invoice,
    supplier_name_raw: str | None,
    is_new_supplier: bool,
) -> list[str]:
    settings = get_settings()
    tolerance = settings.tolerance_total
    codes: list[str] = []

    if not invoice.lines:
        codes.append("A_NO_LINES")

    line_sum = sum(
        (line.line_total_net or 0.0) for line in invoice.lines
    )
    if invoice.total_ht is not None and abs(line_sum - invoice.total_ht) > tolerance:
        codes.append("A_TOTAL_MISMATCH")

    if (
        not supplier_name_raw
        or not invoice.invoice_number
        or not invoice.invoice_date
        or invoice.total_ht is None
    ):
        codes.append("A_MISSING_FIELD")

    for line in invoice.lines:
        if line.line_type != "ARTICLE":
            continue
        if line.quantity is None or line.unit_price_net is None:
            codes.append("A_BAD_LINE")
            break

    unmapped = False
    for line in invoice.lines:
        if line.line_type != "ARTICLE":
            continue
        mapping = await resolve_mapping(db, invoice.supplier_id, line.supplier_ref, line.size)
        if mapping is None:
            unmapped = True
            break
    if unmapped:
        codes.append("A_UNMAPPED_REF")

    if (
        invoice.total_ht is not None
        and invoice.total_vat is not None
        and invoice.total_ttc is not None
        and abs((invoice.total_ht + invoice.total_vat) - invoice.total_ttc) > tolerance
    ):
        codes.append("A_TOTALS_INCONSISTENT")

    if any(_line_low_confidence(line.raw) for line in invoice.lines):
        codes.append("A_LOW_CONFIDENCE")

    if await find_duplicate_candidate(db, invoice) is not None:
        codes.append("A_POSSIBLE_DUPLICATE")

    if is_new_supplier:
        codes.append("A_NEW_SUPPLIER")

    return codes


def _line_low_confidence(raw_json: str | None) -> bool:
    if not raw_json:
        return False
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return False
    return bool(data.get("low_confidence"))


def status_from_anomalies(codes: list[str]) -> str:
    blocking = [c for c in codes if c not in NON_BLOCKING_ANOMALIES]
    return "NEEDS_REVIEW" if blocking else "VALIDATED"


def can_validate(codes: list[str]) -> bool:
    """Le bouton « Valider » n'est bloqué que par ces deux anomalies (§8.3) —
    les autres (dont A_UNMAPPED_REF) n'empêchent pas une validation manuelle."""
    return not any(c in codes for c in VALIDATE_BLOCKING_ANOMALIES)
