from datetime import datetime

from app.db import SessionLocal
from app.checks.netprobe import PhaseAResult, PhaseBResult
from app.checks.xray_adapter import PhaseCResult
from app.models import Check, DailyAggregate, Job, Server, ServerAlias
from app.services import scanner as scanner_module
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


def test_scan_server_fails_when_phase_a_success_but_phase_b_has_no_successes(monkeypatch) -> None:
    session = SessionLocal()
    try:
        server = Server(name="srv", host="example.com", port=443)
        session.add(server)
        session.commit()
        session.refresh(server)

        monkeypatch.setattr(
            scanner_module,
            "phase_a_dns_tcp",
            lambda host, port, timeout_s: PhaseAResult(
                success=True,
                dns_ok=True,
                ip="127.0.0.1",
                rtt_ms=25.0,
                error_type=None,
                error_message=None,
            ),
        )
        monkeypatch.setattr(
            scanner_module,
            "phase_b_multi_tcp",
            lambda host, port, timeout_s, attempts: PhaseBResult(
                attempts=attempts,
                successes=0,
                success_rate=0.0,
                rtt_min_ms=None,
                rtt_median_ms=None,
                rtt_max_ms=None,
                jitter_ms=None,
                stopped_early=False,
                samples=tuple(),
            ),
        )

        service = ScannerService()
        monkeypatch.setattr(
            service.xray_pool,
            "check_http_via_xray",
            lambda host, port, enabled, timeout_s: PhaseCResult(
                enabled=False,
                available=False,
                success=False,
                latency_ms=None,
                error_message=None,
            ),
        )

        check = service.scan_server(session, server, attempts=3)

        assert check.status == "fail"
        assert check.error_message == "phase_b_has_no_successful_probes"
    finally:
        session.close()


def test_xray_public_api_compatibility() -> None:
    from inspect import signature

    from app.checks.xray_adapter import XrayAdapter
    from app.services.xray_pool import XrayPoolService

    adapter_sig = signature(XrayAdapter.__init__)
    pool_sig = signature(XrayPoolService.__init__)

    assert "max_workers" in adapter_sig.parameters
    assert "max_workers" in pool_sig.parameters

    adapter = XrayAdapter(max_workers=10)
    assert adapter.max_workers == 2
    assert not hasattr(adapter, "pool")
