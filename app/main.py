from contextlib import asynccontextmanager
from pathlib import Path
import shutil

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.utils.logging import configure_logging
from app.utils.preflight import log_preflight_warnings
from app.web.routes import router as web_router
from app.config import settings
from app.services.settings_store import apply_persisted_settings
from app.db import SessionLocal


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    log_preflight_warnings()
    init_db()
    with SessionLocal() as db:
        apply_persisted_settings(db)
    yield


app = FastAPI(title="VLSC API", lifespan=lifespan)
app.include_router(web_router)
_STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/health")
def health_check() -> dict[str, object]:
    return {
        "status": "ok",
        "xray": {
            "enabled": settings.xray_enabled,
            "binary_found": shutil.which("xray") is not None,
        },
    }
