from datetime import datetime

from app.db import SessionLocal
from app.checks.confidence import calculate_confidence
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
            latency_samples_total=2,
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
        assert aggregate.latency_samples_total == 3
        assert aggregate.avg_latency_ms == 90.0
    finally:
        session.rollback()
        session.close()


def test_daily_aggregate_ignores_none_latency_and_matches_recompute() -> None:
    session = SessionLocal()
    try:
        server = Server(name="srv", host="none-latency.example.com", port=443)
        session.add(server)
        session.commit()
        session.refresh(server)

        service = ScannerService()
        check_data = [
            ("ok", None),
            ("fail", 120.0),
            ("ok", None),
            ("ok", 60.0),
            ("fail", None),
            ("ok", 90.0),
        ]
        day = datetime(2024, 2, 2, 8, 0, 0)

        for idx, (status, latency) in enumerate(check_data):
            check = Check(
                server_id=server.id,
                status=status,
                latency_ms=latency,
                checked_at=day.replace(hour=8 + idx),
            )
            session.add(check)
            session.flush()
            service._update_daily_aggregate(session, check)

        aggregate = (
            session.query(DailyAggregate)
            .filter(DailyAggregate.server_id == server.id, DailyAggregate.day == day.date())
            .one()
        )

        assert aggregate.checks_total == 6
        assert aggregate.success_total == 4
        assert aggregate.latency_samples_total == 3
        assert aggregate.avg_latency_ms == 90.0

        recomputed = service.recompute_daily_aggregate(session, server.id, day.date())

        assert recomputed.checks_total == aggregate.checks_total
        assert recomputed.success_total == aggregate.success_total
        assert recomputed.latency_samples_total == aggregate.latency_samples_total
        assert recomputed.avg_latency_ms == aggregate.avg_latency_ms
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


def test_scan_server_with_previous_check_does_not_fail_confidence_datetime_math(monkeypatch) -> None:
    session = SessionLocal()
    try:
        server = Server(name="srv", host="example.com", port=443)
        session.add(server)
        session.commit()
        session.refresh(server)

        previous = Check(
            server_id=server.id,
            status="ok",
            latency_ms=15.0,
            checked_at=datetime(2024, 1, 1, 9, 0, 0),
        )
        session.add(previous)
        session.commit()

        monkeypatch.setattr(
            scanner_module,
            "phase_a_dns_tcp",
            lambda host, port, timeout_s: PhaseAResult(
                success=True,
                dns_ok=True,
                ip="127.0.0.1",
                rtt_ms=20.0,
                error_type=None,
                error_message=None,
            ),
        )
        monkeypatch.setattr(
            scanner_module,
            "phase_b_multi_tcp",
            lambda host, port, timeout_s, attempts: PhaseBResult(
                attempts=attempts,
                successes=attempts,
                success_rate=1.0,
                rtt_min_ms=18.0,
                rtt_median_ms=20.0,
                rtt_max_ms=22.0,
                jitter_ms=2.0,
                stopped_early=False,
                samples=(18.0, 20.0, 22.0),
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

        assert check.status == "ok"
        assert check.confidence is not None
        assert 0.0 <= check.confidence <= 1.0
    finally:
        session.close()


def test_build_confidence_input_check_granularity_monotonicity() -> None:
    session = SessionLocal()
    try:
        server = Server(name="srv", host="example.com", port=443)
        session.add(server)
        session.commit()
        session.refresh(server)

        service = ScannerService()

        success_confidences: list[float] = []
        for _ in range(3):
            metrics = service._build_confidence_input(session, server.id, current_check_ok=True, jitter_ms=None)
            confidence = calculate_confidence(metrics).confidence
            success_confidences.append(confidence)

            session.add(Check(server_id=server.id, status="ok", latency_ms=10.0))
            session.commit()

        assert success_confidences[0] <= success_confidences[1] <= success_confidences[2]

        fail_metrics = service._build_confidence_input(session, server.id, current_check_ok=False, jitter_ms=None)
        fail_confidence = calculate_confidence(fail_metrics).confidence

        success_metrics = service._build_confidence_input(session, server.id, current_check_ok=True, jitter_ms=None)
        success_confidence = calculate_confidence(success_metrics).confidence

        assert fail_confidence < success_confidence
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


def test_scan_server_xray_only_skips_phase_a_and_b(monkeypatch) -> None:
    session = SessionLocal()
    try:
        server = Server(name="srv", host="xray-only.example.com", port=443)
        session.add(server)
        session.commit()
        session.refresh(server)

        def _phase_a_should_not_run(host, port, timeout_s):
            raise AssertionError("phase_a_dns_tcp should not be called in xray_only mode")

        def _phase_b_should_not_run(host, port, timeout_s, attempts):
            raise AssertionError("phase_b_multi_tcp should not be called in xray_only mode")

        monkeypatch.setattr(scanner_module, "phase_a_dns_tcp", _phase_a_should_not_run)
        monkeypatch.setattr(scanner_module, "phase_b_multi_tcp", _phase_b_should_not_run)

        service = ScannerService()
        monkeypatch.setattr(
            service.xray_pool,
            "check_http_via_xray",
            lambda host, port, enabled, timeout_s: PhaseCResult(
                enabled=True,
                available=True,
                success=True,
                latency_ms=123.0,
                error_message=None,
            ),
        )

        check = service.scan_server(session, server, attempts=3, scan_strategy="xray_only")

        assert check.status == "ok"
        assert check.score == 100
        assert check.error_message is None
        assert isinstance(check.details_json, dict)
        assert check.details_json["scan_strategy"] == "xray_only"
        assert check.details_json["phase_a"]["skipped"] is True
        assert check.details_json["phase_b"]["skipped"] is True
    finally:
        session.close()


def test_scan_server_xray_only_uses_phase_c_result_for_status_and_error(monkeypatch) -> None:
    session = SessionLocal()
    try:
        server = Server(name="srv", host="xray-fail.example.com", port=8443)
        session.add(server)
        session.commit()
        session.refresh(server)

        monkeypatch.setattr(scanner_module, "phase_a_dns_tcp", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("phase_a should not run")))
        monkeypatch.setattr(scanner_module, "phase_b_multi_tcp", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("phase_b should not run")))

        service = ScannerService()
        monkeypatch.setattr(
            service.xray_pool,
            "check_http_via_xray",
            lambda host, port, enabled, timeout_s: PhaseCResult(
                enabled=True,
                available=True,
                success=False,
                latency_ms=None,
                error_message="xray downstream timeout",
            ),
        )

        check = service.scan_server(session, server, attempts=3, scan_strategy="xray_only")

        assert check.status == "fail"
        assert check.score == 0
        assert check.error_message == "xray downstream timeout"
    finally:
        session.close()
