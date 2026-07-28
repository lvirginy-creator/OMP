from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


def _placeholder(request: Request, title: str, note: str):
    return templates.TemplateResponse(
        request, "placeholder.html", {"title": title, "note": note}
    )


@router.get("/factures")
def factures(request: Request):
    return _placeholder(request, "Factures", "arrive à l'étape 3")


@router.get("/a-mapper")
def a_mapper(request: Request):
    return _placeholder(request, "Références à mapper", "arrive à l'étape 6")


@router.get("/export")
def export(request: Request):
    return _placeholder(request, "Export", "arrive à l'étape 7")


@router.get("/journal")
def journal(request: Request):
    return _placeholder(request, "Journal", "arrive à l'étape 8")
