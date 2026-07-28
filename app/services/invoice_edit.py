import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_log import ImportLog
from app.models.invoice import Invoice, InvoiceLine
from app.models.supplier import Supplier
from app.services.anomalies import can_validate, compute_anomalies, status_from_anomalies
from app.services.normalize import normalize_supplier_name
from app.services.suppliers import get_or_create_supplier, now_iso


@dataclass
class SaveResult:
    ok: bool
    message: str | None = None


async def save_invoice_edits(
    db: AsyncSession, invoice: Invoice, header: dict, lines: list[dict]
) -> SaveResult:
    """Enregistre les corrections manuelles de l'écran de vérification (§8.3).
    Remplace intégralement les lignes (pas de réconciliation par id : plus simple
    et fiable pour un volume de quelques dizaines de lignes par facture)."""
    supplier: Supplier | None = None
    is_new_supplier = False
    supplier_name_raw = (header.get("supplier_name") or "").strip() or None
    if supplier_name_raw:
        normalized = normalize_supplier_name(supplier_name_raw)
        existing_supplier = (
            await db.execute(select(Supplier).where(Supplier.normalized_name == normalized))
        ).scalar_one_or_none()
        is_new_supplier = existing_supplier is None
        supplier = await get_or_create_supplier(db, supplier_name_raw)

    new_invoice_number = header.get("invoice_number")

    invoice.supplier_id = supplier.id if supplier else None
    invoice.document_type = header.get("document_type") or "INVOICE"
    invoice.invoice_number = new_invoice_number
    invoice.invoice_date = header.get("invoice_date")
    invoice.currency = header.get("currency") or "EUR"
    invoice.total_ht = header.get("total_ht")
    invoice.total_vat = header.get("total_vat")
    invoice.total_ttc = header.get("total_ttc")

    for line in list(invoice.lines):
        await db.delete(line)

    for idx, line in enumerate(lines, start=1):
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
                vat_rate=None,
                raw=json.dumps({"source": "manual_edit"}),
            )
        )

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return SaveResult(
            ok=False,
            message=(
                f"Cette facture n° {new_invoice_number} est déjà utilisée pour ce "
                "fournisseur et ce type de document."
            ),
        )

    await db.refresh(invoice, attribute_names=["lines"])
    codes = await compute_anomalies(db, invoice, supplier_name_raw, is_new_supplier)
    invoice.anomalies = json.dumps(codes)
    invoice.status = status_from_anomalies(codes)
    invoice.validated_at = now_iso() if invoice.status == "VALIDATED" else None

    await db.commit()
    return SaveResult(ok=True)


async def force_validate(db: AsyncSession, invoice: Invoice) -> SaveResult:
    codes = json.loads(invoice.anomalies) if invoice.anomalies else []
    if not can_validate(codes):
        return SaveResult(ok=False, message="Total incohérent ou champ obligatoire manquant.")
    invoice.status = "VALIDATED"
    invoice.validated_at = now_iso()
    await db.commit()
    return SaveResult(ok=True)


async def delete_invoice(db: AsyncSession, invoice: Invoice, pdfs_deleted_dir: Path) -> None:
    """§6.1 Annulation : cascade sur les lignes, PDF conservé 30 jours, journalisé."""
    stored_path = Path(invoice.stored_path) if invoice.stored_path else None
    invoice_id = invoice.id
    invoice_number = invoice.invoice_number

    if stored_path and stored_path.exists():
        pdfs_deleted_dir.mkdir(parents=True, exist_ok=True)
        stored_path.rename(pdfs_deleted_dir / stored_path.name)

    db.add(
        ImportLog(
            kind="INVOICE",
            filename=stored_path.name if stored_path else "?",
            invoice_id=None,
            outcome="DELETED",
            message=f"Facture n° {invoice_number or '(sans numéro)'} (id {invoice_id}) supprimée",
            created_at=now_iso(),
        )
    )
    await db.delete(invoice)
    await db.commit()
