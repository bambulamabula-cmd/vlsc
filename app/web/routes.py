from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.models import Check, Job, Server
from app.services.retention import RetentionService
from app.vless.parser import VlessParseError, parse_vless_uri

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")

def _scan_state_from_job(job: Job | None) -> dict[str, object]:
    mode = "quick"
    if job and job.payload and isinstance(job.payload, dict):
        mode = str(job.payload.get("mode") or mode)

    running = bool(job and job.status == "running")
    started_at = job.started_at.isoformat() if running and job and job.started_at else None
    progress = 1 if running else 100

    return {
        "running": running,
        "mode": mode,
        "started_at": started_at,
        "progress": progress,
        "job_id": job.id if running and job else None,
    }


def _active_scan_job(db: Session) -> Job | None:
    return db.query(Job).filter(Job.kind == "scan", Job.status == "running").order_by(Job.id.desc()).first()


def _latest_checks_map(db: Session, server_ids: list[int]) -> dict[int, Check]:
    if not server_ids:
        return {}

    ranked_checks = (
        db.query(
            Check.id.label("check_id"),
            Check.server_id.label("server_id"),
            func.row_number()
            .over(
                partition_by=Check.server_id,
                order_by=(Check.checked_at.desc(), Check.id.desc()),
            )
            .label("rank"),
        )
        .filter(Check.server_id.in_(server_ids))
        .subquery()
    )

    checks = (
        db.query(Check)
        .join(ranked_checks, ranked_checks.c.check_id == Check.id)
        .filter(ranked_checks.c.rank == 1)
        .all()
    )
    return {check.server_id: check for check in checks}


def _serialize_server(server: Server, last_check: Check | None = None) -> dict[str, object]:
    xray = None
    if last_check and last_check.details_json:
        phase_c = last_check.details_json.get("phase_c", {})
        xray = phase_c.get("success")

    return {
        "id": server.id,
        "name": server.name,
        "host": server.host,
        "port": server.port,
        "enabled": server.enabled,
        "alive": bool(last_check and last_check.status == "ok"),
        "xray_ok": xray,
        "score": last_check.score if last_check else None,
        "last_error": last_check.error_message if last_check else None,
        "updated_at": server.updated_at.isoformat(),
    }


def _parse_import_payload(raw_text: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    parsed: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []

    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            parsed_uri = parse_vless_uri(candidate)
            parsed.append(parsed_uri.model_dump(mode="json"))
        except VlessParseError as exc:
            errors.append({"line": line_number, "uri": candidate, "error": str(exc)})

    return parsed, errors


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db_session)):
    servers = db.query(Server).order_by(Server.updated_at.desc()).all()
    latest_checks = _latest_checks_map(db, [server.id for server in servers])
    items = [_serialize_server(server, latest_checks.get(server.id)) for server in servers]

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "VLSC Dashboard",
            "servers": items,
            "alive_total": len([s for s in items if s["alive"]]),
            "xray_total": len([s for s in items if s["xray_ok"] is True]),
            "scan_state": _scan_state_from_job(_active_scan_job(db)),
        },
    )


@router.get("/scan", response_class=HTMLResponse)
def scan_page(request: Request, db: Session = Depends(get_db_session)):
    last_job = db.query(Job).order_by(Job.created_at.desc()).first()
    return templates.TemplateResponse(
        "scan.html",
        {
            "request": request,
            "title": "Scan Servers",
            "scan_state": _scan_state_from_job(_active_scan_job(db)),
            "last_job": last_job,
        },
    )


@router.get("/servers/{server_id}", response_class=HTMLResponse)
def server_details(request: Request, server_id: int, db: Session = Depends(get_db_session)):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    history = (
        db.query(Check)
        .filter(Check.server_id == server_id)
        .order_by(Check.checked_at.desc())
        .limit(30)
        .all()
    )
    latest = history[0] if history else None
    sparkline = [int(check.score or 0) for check in reversed(history)]

    return templates.TemplateResponse(
        "server_details.html",
        {
            "request": request,
            "title": f"Server #{server_id}",
            "server": server,
            "history": history,
            "latest": latest,
            "sparkline": sparkline,
        },
    )


@router.post("/api/import")
async def import_uris(
    db: Session = Depends(get_db_session),
    uris_text: str = Form(default=""),
    uris_file: UploadFile | None = File(default=None),
):
    chunks: list[str] = []
    if uris_text.strip():
        chunks.append(uris_text)

    if uris_file is not None:
        filename = (uris_file.filename or "").lower()
        if not filename.endswith(".txt"):
            raise HTTPException(status_code=400, detail="Only .txt files are supported")
        payload = await uris_file.read()
        chunks.append(payload.decode("utf-8", errors="replace"))

    if not chunks:
        raise HTTPException(status_code=400, detail="No URIs provided")

    parsed, errors = _parse_import_payload("\n".join(chunks))

    created = 0
    skipped_duplicates = 0
    for item in parsed:
        host = item["host"]
        port = item["port"]
        name = item.get("name") or f"{host}:{port}"

        existing = db.query(Server).filter(Server.host == host, Server.port == port).first()
        if existing:
            skipped_duplicates += 1
            continue

        db.add(Server(name=name, host=host, port=port, metadata_json=item))
        created += 1

    db.commit()

    return {
        "accepted": len(parsed),
        "created": created,
        "skipped_duplicates": skipped_duplicates,
        "errors": errors,
    }


@router.post("/api/scan/start")
def start_scan(mode: str = Form(default="quick"), db: Session = Depends(get_db_session)):
    now = datetime.now(timezone.utc)
    job = Job(kind="scan", status="running", payload={"mode": mode}, started_at=now)

    try:
        with db.begin():
            db.add(job)
            db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Scan already running") from None

    db.refresh(job)
    return {"job_id": job.id, "scan_state": _scan_state_from_job(job)}


@router.post("/api/scan/stop")
def stop_scan(db: Session = Depends(get_db_session)):
    running_job = _active_scan_job(db)
    if running_job:
        running_job.status = "stopped"
        running_job.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(running_job)

    return {
        "scan_state": _scan_state_from_job(_active_scan_job(db)),
        "stopped_job_id": running_job.id if running_job else None,
    }


@router.get("/api/servers")
def list_servers(
    db: Session = Depends(get_db_session),
    alive: bool | None = Query(default=None),
    xray: bool | None = Query(default=None),
    top: int | None = Query(default=None, ge=1, le=1000),
    sort: str = Query(default="updated_desc"),
):
    servers = db.query(Server).order_by(Server.updated_at.desc()).all()
    latest_checks = _latest_checks_map(db, [server.id for server in servers])
    items = [_serialize_server(server, latest_checks.get(server.id)) for server in servers]

    if alive is not None:
        items = [item for item in items if item["alive"] is alive]
    if xray is not None:
        items = [item for item in items if item["xray_ok"] is xray]

    if sort == "score_desc":
        items.sort(key=lambda x: ((x["score"] is None), -(x["score"] or 0)))
    elif sort == "score_asc":
        items.sort(key=lambda x: (x["score"] is None, (x["score"] or 0)))
    elif sort == "name_asc":
        items.sort(key=lambda x: str(x["name"]).lower())
    else:
        items.sort(key=lambda x: str(x["updated_at"]), reverse=True)

    if top is not None:
        items = items[:top]

    return {"items": items, "total": len(items)}


@router.get("/api/servers/{server_id}")
def get_server(server_id: int, db: Session = Depends(get_db_session)):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    history = (
        db.query(Check)
        .filter(Check.server_id == server_id)
        .order_by(Check.checked_at.desc())
        .limit(50)
        .all()
    )
    return {
        "server": _serialize_server(server, history[0] if history else None),
        "history": [
            {
                "id": check.id,
                "status": check.status,
                "latency_ms": check.latency_ms,
                "error_message": check.error_message,
                "score": check.score,
                "confidence": check.confidence,
                "checked_at": check.checked_at.isoformat(),
                "score_explain": (check.details_json or {}).get("score_explain"),
            }
            for check in history
        ],
    }


@router.get("/api/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db_session)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "payload": job.payload,
        "result": job.result,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "created_at": job.created_at.isoformat(),
    }


@router.get("/api/export")
def export_servers(db: Session = Depends(get_db_session)):
    servers = db.query(Server).order_by(Server.id.asc()).all()
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["id", "name", "host", "port", "enabled", "updated_at"])
    for server in servers:
        writer.writerow([server.id, server.name, server.host, server.port, server.enabled, server.updated_at.isoformat()])

    return StreamingResponse(
        iter([stream.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=servers_export.csv"},
    )


@router.post("/api/retention/cleanup")
def run_cleanup(
    db: Session = Depends(get_db_session),
    raw_days: int = Form(default=30),
    aggregate_days: int = Form(default=365),
    vacuum: bool = Form(default=True),
):
    retention = RetentionService()
    report = retention.cleanup(db=db, raw_checks_days=raw_days, aggregate_days=aggregate_days, run_vacuum=vacuum)
    return JSONResponse(report)
