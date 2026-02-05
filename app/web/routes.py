from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "VLSC Dashboard",
        },
    )


@router.get("/scan", response_class=HTMLResponse)
def scan_page(request: Request):
    return templates.TemplateResponse(
        "scan.html",
        {
            "request": request,
            "title": "Scan Servers",
        },
    )


@router.get("/servers/{server_id}", response_class=HTMLResponse)
def server_details(request: Request, server_id: int):
    return templates.TemplateResponse(
        "server_details.html",
        {
            "request": request,
            "title": f"Server #{server_id}",
            "server_id": server_id,
        },
    )
