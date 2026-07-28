import uuid

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.import_log import ImportLog
from app.models.mapping import Mapping
from app.models.supplier import Supplier
from app.services.excel_mappings import (
    ParseResult,
    apply_import,
    build_preview,
    export_mappings,
    generate_template,
    parse_workbook,
)
from app.services.suppliers import merge_suppliers, now_iso

router = APIRouter(prefix="/referentiel")
templates = Jinja2Templates(directory="app/templates")

# Cache en mémoire des imports en attente de confirmation (app mono-utilisateur, un seul worker).
_pending_imports: dict[str, tuple[str, ParseResult]] = {}


async def _load_mappings(db: AsyncSession, q: str | None):
    stmt = select(Mapping, Supplier.name).outerjoin(
        Supplier, Mapping.supplier_id == Supplier.id
    )
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                Mapping.supplier_ref.ilike(like),
                Mapping.supplier_label.ilike(like),
                Mapping.our_ref.ilike(like),
                Mapping.our_label.ilike(like),
                Mapping.ean.ilike(like),
                Supplier.name.ilike(like),
            )
        )
    stmt = stmt.order_by(Supplier.name.is_(None), Supplier.name, Mapping.supplier_ref)
    result = await db.execute(stmt)
    return result.all()


@router.get("", response_class=HTMLResponse)
async def list_mappings(
    request: Request,
    q: str | None = None,
    merge_error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    rows = await _load_mappings(db, q)
    suppliers = (await db.execute(select(Supplier).order_by(Supplier.name))).scalars().all()
    return templates.TemplateResponse(
        request,
        "referentiel/list.html",
        {"rows": rows, "q": q or "", "suppliers": suppliers, "merge_error": merge_error},
    )


@router.post("/fournisseurs/{supplier_id}/rename")
async def rename_supplier(supplier_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    new_name = str(form.get("name", "")).strip()
    supplier = await db.get(Supplier, supplier_id)
    if supplier is None or not new_name:
        return Response(status_code=404)
    supplier.name = new_name
    await db.commit()
    return RedirectResponse("/referentiel", status_code=303)


@router.post("/fournisseurs/{supplier_id}/merge")
async def merge_supplier_route(
    supplier_id: int, target_id: int = Form(...), db: AsyncSession = Depends(get_db)
):
    try:
        await merge_suppliers(db, keep_id=target_id, absorbed_id=supplier_id)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return RedirectResponse("/referentiel?merge_error=1", status_code=303)
    return RedirectResponse("/referentiel", status_code=303)


@router.get("/modele")
def download_template():
    content = generate_template()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=modele_referentiel.xlsx"},
    )


@router.get("/export")
async def export(db: AsyncSession = Depends(get_db)):
    content = await export_mappings(db)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=referentiel_actuel.xlsx"},
    )


@router.post("/{mapping_id}/edit", response_class=HTMLResponse)
async def edit_mapping(
    mapping_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    mapping = await db.get(Mapping, mapping_id)
    if mapping is None:
        return Response(status_code=404)

    mapping.our_ref = str(form.get("our_ref", "")).strip() or mapping.our_ref
    mapping.our_label = str(form.get("our_label", "")).strip() or mapping.our_label
    mapping.ean = str(form.get("ean", "")).strip() or None
    mapping.updated_at = now_iso()
    await db.commit()

    supplier_name = None
    if mapping.supplier_id:
        supplier = await db.get(Supplier, mapping.supplier_id)
        supplier_name = supplier.name if supplier else None

    return templates.TemplateResponse(
        request,
        "referentiel/_row.html",
        {"mapping": mapping, "supplier_name": supplier_name},
    )


@router.get("/{mapping_id}/row", response_class=HTMLResponse)
async def view_row(mapping_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    mapping = await db.get(Mapping, mapping_id)
    if mapping is None:
        return Response(status_code=404)
    supplier_name = None
    if mapping.supplier_id:
        supplier = await db.get(Supplier, mapping.supplier_id)
        supplier_name = supplier.name if supplier else None
    return templates.TemplateResponse(
        request,
        "referentiel/_row.html",
        {"mapping": mapping, "supplier_name": supplier_name},
    )


@router.get("/{mapping_id}/edit-form", response_class=HTMLResponse)
async def edit_form(mapping_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    mapping = await db.get(Mapping, mapping_id)
    if mapping is None:
        return Response(status_code=404)
    supplier_name = None
    if mapping.supplier_id:
        supplier = await db.get(Supplier, mapping.supplier_id)
        supplier_name = supplier.name if supplier else None
    return templates.TemplateResponse(
        request,
        "referentiel/_row_edit.html",
        {"mapping": mapping, "supplier_name": supplier_name},
    )


@router.post("/{mapping_id}/toggle", response_class=HTMLResponse)
async def toggle_mapping(mapping_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    mapping = await db.get(Mapping, mapping_id)
    if mapping is None:
        return Response(status_code=404)
    mapping.active = not mapping.active
    mapping.updated_at = now_iso()
    await db.commit()

    supplier_name = None
    if mapping.supplier_id:
        supplier = await db.get(Supplier, mapping.supplier_id)
        supplier_name = supplier.name if supplier else None

    return templates.TemplateResponse(
        request,
        "referentiel/_row.html",
        {"mapping": mapping, "supplier_name": supplier_name},
    )


@router.post("/import/preview", response_class=HTMLResponse)
async def import_preview(
    request: Request, file: UploadFile, db: AsyncSession = Depends(get_db)
):
    content = await file.read()
    parsed = parse_workbook(content)

    if parsed.header_errors:
        return templates.TemplateResponse(
            request,
            "referentiel/import_errors.html",
            {"errors": parsed.header_errors},
        )

    outcomes = await build_preview(db, parsed)
    await db.rollback()  # build_preview ne crée des fournisseurs qu'en session, non committé

    token = uuid.uuid4().hex
    _pending_imports[token] = (file.filename or "import.xlsx", parsed)

    counts = {
        "create": sum(1 for o in outcomes if o.action == "create"),
        "update": sum(1 for o in outcomes if o.action == "update"),
        "ignore": sum(1 for o in outcomes if o.action == "ignore"),
    }

    return templates.TemplateResponse(
        request,
        "referentiel/import_preview.html",
        {"outcomes": outcomes, "counts": counts, "token": token},
    )


@router.post("/import/apply")
async def import_apply(token: str = Form(...), db: AsyncSession = Depends(get_db)):
    pending = _pending_imports.pop(token, None) if token else None
    if pending is None:
        return RedirectResponse("/referentiel", status_code=303)

    filename, parsed = pending
    created, updated, ignored = await apply_import(db, parsed)
    db.add(
        ImportLog(
            kind="MAPPING",
            filename=filename,
            outcome="MAPPINGS_UPSERTED",
            message=f"{created} créés, {updated} mis à jour, {ignored} ignorés",
            created_at=now_iso(),
        )
    )
    await db.commit()
    return RedirectResponse("/referentiel", status_code=303)


@router.post("/import/cancel")
async def import_cancel(token: str = Form(...)):
    _pending_imports.pop(token, None)
    return RedirectResponse("/referentiel", status_code=303)
