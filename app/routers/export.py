from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.societe import Societe
from app.models.supplier import Supplier
from app.services.excel_export import build_export

router = APIRouter(prefix="/export")
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def export_form(request: Request, db: AsyncSession = Depends(get_db)):
    suppliers = (await db.execute(select(Supplier).order_by(Supplier.name))).scalars().all()
    societes = (await db.execute(select(Societe).order_by(Societe.name))).scalars().all()
    return templates.TemplateResponse(
        request, "export/form.html", {"suppliers": suppliers, "societes": societes}
    )


@router.get("/generate")
async def generate(
    request: Request,
    date_du: str | None = None,
    date_au: str | None = None,
    statut: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    supplier_ids = [int(v) for v in request.query_params.getlist("fournisseur_id") if v.strip()]
    societe_ids = [int(v) for v in request.query_params.getlist("societe_id") if v.strip()]
    content, filename = await build_export(
        db,
        date_du or None,
        date_au or None,
        supplier_ids or None,
        statut or None,
        societe_ids or None,
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
