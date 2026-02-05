from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.utils.logging import configure_logging
from app.web.routes import router as web_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    init_db()
    yield


app = FastAPI(title="VLSC API", lifespan=lifespan)
app.include_router(web_router)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
