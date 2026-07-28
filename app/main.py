from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.db import ensure_data_dirs
from app.routers import a_mapper, export, factures, pages, referentiel


def run_migrations() -> None:
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_data_dirs()
    run_migrations()
    yield


app = FastAPI(title="Suivi des achats", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(pages.router)
app.include_router(referentiel.router)
app.include_router(factures.router)
app.include_router(a_mapper.router)
app.include_router(export.router)


@app.get("/health")
def health():
    return {"status": "ok"}
