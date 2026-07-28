import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.db import get_db
from app.models.invoice import Invoice, InvoiceLine
from app.models.supplier import Supplier
from app.services.invoice_pipeline import process_uploaded_pdf, reextract_invoice

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["fromjson"] = json.loads


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    review_count = (
        await db.execute(select(Invoice).where(Invoice.status == "NEEDS_REVIEW"))
    ).scalars().all()

    unmapped_refs = (
        await db.execute(
            select(InvoiceLine.supplier_ref, Invoice.supplier_id)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(InvoiceLine.line_type == "ARTICLE", InvoiceLine.supplier_ref.is_not(None))
        )
    ).all()
    from app.services.mapping_resolution import resolve_mapping

    unmapped_keys = set()
    for supplier_ref, supplier_id in unmapped_refs:
        mapping = await resolve_mapping(db, supplier_id, supplier_ref)
        if mapping is None:
            unmapped_keys.add((supplier_id, supplier_ref.strip().upper()))

    from datetime import datetime, timezone

    month_prefix = datetime.now(timezone.utc).strftime("%Y-%m")
    this_month = (
        await db.execute(
            select(Invoice).where(Invoice.invoice_date.like(f"{month_prefix}%"))
        )
    ).scalars().all()

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "review_count": len(review_count),
            "unmapped_count": len(unmapped_keys),
            "month_count": len(this_month),
        },
    )


@router.post("/factures/upload", response_class=HTMLResponse)
async def upload(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    files = form.getlist("files")

    results = []
    for f in files:
        if isinstance(f, str):
            continue
        content = await f.read()
        outcome = await process_uploaded_pdf(db, f.filename or "facture.pdf", content)
        results.append({"filename": f.filename, "result": outcome})

    return templates.TemplateResponse(
        request, "factures/_upload_results.html", {"results": results}
    )


@router.get("/factures", response_class=HTMLResponse)
async def list_factures(
    request: Request,
    statut: str | None = None,
    type: str | None = None,
    fournisseur_id: int | None = None,
    date_du: str | None = None,
    date_au: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Invoice, Supplier.name)
        .outerjoin(Supplier, Invoice.supplier_id == Supplier.id)
        .options(selectinload(Invoice.lines))
    )
    if statut:
        stmt = stmt.where(Invoice.status == statut)
    if type:
        stmt = stmt.where(Invoice.document_type == type)
    if fournisseur_id:
        stmt = stmt.where(Invoice.supplier_id == fournisseur_id)
    if date_du:
        stmt = stmt.where(Invoice.invoice_date >= date_du)
    if date_au:
        stmt = stmt.where(Invoice.invoice_date <= date_au)
    stmt = stmt.order_by(Invoice.invoice_date.desc().nullslast(), Invoice.id.desc())

    rows = (await db.execute(stmt)).all()
    suppliers = (await db.execute(select(Supplier).order_by(Supplier.name))).scalars().all()

    return templates.TemplateResponse(
        request,
        "factures/list.html",
        {
            "rows": rows,
            "suppliers": suppliers,
            "statut": statut or "",
            "type": type or "",
            "fournisseur_id": fournisseur_id or "",
            "date_du": date_du or "",
            "date_au": date_au or "",
        },
    )


@router.get("/factures/{invoice_id}", response_class=HTMLResponse)
async def detail(invoice_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None:
        return Response(status_code=404)
    await db.refresh(invoice, attribute_names=["lines"])
    supplier = await db.get(Supplier, invoice.supplier_id) if invoice.supplier_id else None
    anomalies = json.loads(invoice.anomalies) if invoice.anomalies else []
    diagnostics = json.loads(invoice.raw_diagnostics) if invoice.raw_diagnostics else {}

    return templates.TemplateResponse(
        request,
        "factures/detail.html",
        {
            "invoice": invoice,
            "supplier": supplier,
            "anomalies": anomalies,
            "diagnostics": diagnostics,
        },
    )


@router.get("/factures/{invoice_id}/pdf")
async def get_pdf(invoice_id: int, db: AsyncSession = Depends(get_db)):
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None or not invoice.stored_path:
        return Response(status_code=404)

    settings = get_settings()
    path = Path(invoice.stored_path).resolve()
    if settings.pdfs_path.resolve() not in path.parents:
        return Response(status_code=404)
    if not path.exists():
        return Response(status_code=404)

    return FileResponse(path, media_type="application/pdf")


@router.post("/factures/{invoice_id}/reextract")
async def reextract(invoice_id: int, db: AsyncSession = Depends(get_db)):
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None:
        return Response(status_code=404)
    await reextract_invoice(db, invoice, force_vision=False)
    return RedirectResponse(f"/factures/{invoice_id}", status_code=303)


@router.post("/factures/{invoice_id}/reextract-vision")
async def reextract_vision(invoice_id: int, db: AsyncSession = Depends(get_db)):
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None:
        return Response(status_code=404)
    await reextract_invoice(db, invoice, force_vision=True)
    return RedirectResponse(f"/factures/{invoice_id}", status_code=303)
