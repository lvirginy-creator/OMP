from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.import_log import ImportLog

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/journal", response_class=HTMLResponse)
async def journal(request: Request, db: AsyncSession = Depends(get_db)):
    entries = (
        await db.execute(select(ImportLog).order_by(ImportLog.created_at.desc()))
    ).scalars().all()
    return templates.TemplateResponse(request, "journal.html", {"entries": entries})
