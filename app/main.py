from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import Base, engine
from app.web.routes import router as web_router

app = FastAPI(title="VLSC API")


@app.on_event("startup")
def init_database() -> None:
    Base.metadata.create_all(bind=engine)
app.include_router(web_router)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
