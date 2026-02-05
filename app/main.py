from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.utils.logging import configure_logging
from app.utils.preflight import run_preflight_checks
from app.web.routes import router as web_router
from app.config import settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    run_preflight_checks(sqlite_path=settings.sqlite_path, xray_enabled=settings.xray_enabled)
    init_db()
    yield


app = FastAPI(title="VLSC API", lifespan=lifespan)
app.include_router(web_router)
_STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
