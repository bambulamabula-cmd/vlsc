from datetime import datetime

from app.db import SessionLocal
from app.models import Check, DailyAggregate, Job, Server, ServerAlias
from app.services.scanner import ScannerService


def setup_function() -> None:
    session = SessionLocal()
    try:
        session.query(Check).delete()
        session.query(DailyAggregate).delete()
        session.query(ServerAlias).delete()
        session.query(Server).delete()
        session.query(Job).delete()
        session.commit()
    finally:
        session.close()


def test_update_daily_aggregate_uses_incremental_online_average() -> None:
    session = SessionLocal()
    try:
        server = Server(name="srv", host="inc.example.com", port=443)
        session.add(server)
        session.flush()

        day = datetime(2024, 1, 1, 10, 0, 0)
        aggregate = DailyAggregate(
            server_id=server.id,
            day=day.date(),
            checks_total=2,
            success_total=1,
            avg_latency_ms=100.0,
        )
        session.add(aggregate)

        check = Check(
            server_id=server.id,
            status="ok",
            latency_ms=70.0,
            checked_at=day,
        )
        session.add(check)
        session.flush()

        ScannerService()._update_daily_aggregate(session, check)

        assert aggregate.checks_total == 3
        assert aggregate.success_total == 2
        assert aggregate.avg_latency_ms == 90.0
    finally:
        session.rollback()
        session.close()
