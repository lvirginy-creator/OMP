from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.societe import Societe
from app.services.suppliers import now_iso

router = APIRouter(prefix="/societes")
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def list_societes(request: Request, db: AsyncSession = Depends(get_db)):
    societes = (await db.execute(select(Societe).order_by(Societe.name))).scalars().all()
    return templates.TemplateResponse(request, "societes/list.html", {"societes": societes})


@router.post("/create")
async def create_societe(name: str = Form(...), db: AsyncSession = Depends(get_db)):
    name = name.strip()
    if name:
        db.add(Societe(name=name, active=True, created_at=now_iso()))
        await db.commit()
    return RedirectResponse("/societes", status_code=303)


@router.post("/{societe_id}/rename")
async def rename_societe(societe_id: int, name: str = Form(...), db: AsyncSession = Depends(get_db)):
    societe = await db.get(Societe, societe_id)
    name = name.strip()
    if societe and name:
        societe.name = name
        await db.commit()
    return RedirectResponse("/societes", status_code=303)


@router.post("/{societe_id}/toggle")
async def toggle_societe(societe_id: int, db: AsyncSession = Depends(get_db)):
    societe = await db.get(Societe, societe_id)
    if societe:
        societe.active = not societe.active
        await db.commit()
    return RedirectResponse("/societes", status_code=303)
