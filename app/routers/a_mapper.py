from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.services.mapping_queue import create_mapping_and_recompute, get_unmapped_groups

router = APIRouter(prefix="/a-mapper")
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def list_unmapped(request: Request, db: AsyncSession = Depends(get_db)):
    groups = await get_unmapped_groups(db)
    return templates.TemplateResponse(request, "a_mapper/list.html", {"groups": groups})


@router.post("/create", response_class=HTMLResponse)
async def create(
    request: Request,
    supplier_id: str = Form(""),
    supplier_ref: str = Form(...),
    size: str = Form(""),
    our_ref: str = Form(...),
    our_label: str = Form(...),
    ean: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    sid = int(supplier_id) if supplier_id.strip() else None
    await create_mapping_and_recompute(
        db, sid, supplier_ref.strip(), our_ref.strip(), our_label.strip(), ean.strip(), size.strip()
    )
    return HTMLResponse(
        '<tr><td colspan="11">✓ Référence mappée.</td></tr>'
    )
