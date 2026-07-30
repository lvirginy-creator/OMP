import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice, InvoiceLine
from app.models.mapping import Mapping
from app.models.supplier import Supplier
from app.services.anomalies import compute_anomalies, status_from_anomalies
from app.services.normalize import normalize_ref, normalize_size
from app.services.suppliers import now_iso


@dataclass
class UnmappedGroup:
    supplier_id: int | None
    supplier_name: str | None
    supplier_ref_norm: str
    supplier_ref: str
    supplier_label: str | None
    size: str | None = None
    line_count: int = 0
    total_qty: float = 0.0
    first_date: str | None = None
    last_date: str | None = None


async def get_unmapped_groups(db: AsyncSession) -> list[UnmappedGroup]:
    active_mappings = (
        await db.execute(select(Mapping).where(Mapping.active.is_(True)))
    ).scalars().all()
    specific_keys = {
        (m.supplier_id, m.supplier_ref_norm, m.size) for m in active_mappings if m.supplier_id
    }
    global_keys = {(m.supplier_ref_norm, m.size) for m in active_mappings if m.supplier_id is None}

    rows = (
        await db.execute(
            select(
                Invoice.supplier_id,
                Supplier.name,
                InvoiceLine.supplier_ref,
                InvoiceLine.supplier_ref_norm,
                InvoiceLine.supplier_label,
                InvoiceLine.size,
                InvoiceLine.quantity,
                Invoice.invoice_date,
            )
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .outerjoin(Supplier, Supplier.id == Invoice.supplier_id)
            .where(InvoiceLine.line_type == "ARTICLE", InvoiceLine.supplier_ref.is_not(None))
        )
    ).all()

    groups: dict[tuple[int | None, str, str | None], UnmappedGroup] = {}
    for (
        supplier_id,
        supplier_name,
        supplier_ref,
        ref_norm,
        supplier_label,
        size,
        quantity,
        invoice_date,
    ) in rows:
        if not ref_norm:
            continue
        size_norm = normalize_size(size)
        if (supplier_id, ref_norm, size_norm) in specific_keys or (ref_norm, size_norm) in global_keys:
            continue

        key = (supplier_id, ref_norm, size_norm)
        group = groups.get(key)
        if group is None:
            group = UnmappedGroup(
                supplier_id=supplier_id,
                supplier_name=supplier_name,
                supplier_ref_norm=ref_norm,
                supplier_ref=supplier_ref,
                supplier_label=supplier_label,
                size=size_norm,
            )
            groups[key] = group

        group.line_count += 1
        group.total_qty += quantity or 0.0
        if invoice_date:
            if group.first_date is None or invoice_date < group.first_date:
                group.first_date = invoice_date
            if group.last_date is None or invoice_date > group.last_date:
                group.last_date = invoice_date
        if supplier_label and not group.supplier_label:
            group.supplier_label = supplier_label

    result = list(groups.values())
    result.sort(key=lambda g: (g.supplier_name or "", g.supplier_ref, g.size or "", -g.total_qty))
    return result


async def create_mapping_and_recompute(
    db: AsyncSession,
    supplier_id: int | None,
    supplier_ref: str,
    our_ref: str,
    our_label: str,
    ean: str | None,
    size: str | None = None,
) -> Mapping:
    timestamp = now_iso()
    mapping = Mapping(
        supplier_id=supplier_id,
        supplier_ref=supplier_ref,
        size=normalize_size(size),
        our_ref=our_ref,
        our_label=our_label,
        ean=ean or None,
        active=True,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(mapping)
    await db.flush()

    ref_norm = normalize_ref(supplier_ref)
    stmt = (
        select(Invoice)
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .where(InvoiceLine.line_type == "ARTICLE", InvoiceLine.supplier_ref_norm == ref_norm)
        .distinct()
    )
    if supplier_id:
        stmt = stmt.where(Invoice.supplier_id == supplier_id)

    invoices = (await db.execute(stmt)).scalars().all()
    for invoice in invoices:
        await db.refresh(invoice, attribute_names=["lines"])
        codes = json.loads(invoice.anomalies) if invoice.anomalies else []
        if "A_UNMAPPED_REF" not in codes:
            continue
        supplier = await db.get(Supplier, invoice.supplier_id) if invoice.supplier_id else None
        new_codes = await compute_anomalies(db, invoice, supplier.name if supplier else None, False)
        invoice.anomalies = json.dumps(new_codes)
        new_status = status_from_anomalies(new_codes)
        if new_status == "VALIDATED" and invoice.status != "VALIDATED":
            invoice.validated_at = timestamp
        invoice.status = new_status

    await db.commit()
    return mapping
