from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.checks.confidence import ConfidenceInput, calculate_confidence
from app.checks.netprobe import phase_a_dns_tcp, phase_b_multi_tcp
from app.checks.scoring import explainable_score
from app.config import settings
from app.models import Check, DailyAggregate, Server, normalize_utc_naive
from app.services.xray_pool import XrayPoolService


ScanStrategy = Literal["full_scan", "xray_only"]


class ScannerService:
    def __init__(self, xray_pool: XrayPoolService | None = None) -> None:
        self.xray_pool = xray_pool or XrayPoolService(max_workers=2)

    def scan_server(
        self,
        db: Session,
        server: Server,
        attempts: int = 5,
        scan_strategy: ScanStrategy = "full_scan",
    ) -> Check:
        timeout_s = float(settings.check_timeout_seconds)

        phase_c = self.xray_pool.check_http_via_xray(
            server.host,
            server.port,
            enabled=settings.xray_enabled,
            timeout_s=min(timeout_s, 8.0),
        )

        if scan_strategy == "xray_only":
            status = "ok" if phase_c.success else "fail"
            score_total = 100 if phase_c.success else 0
            error_message = None if phase_c.success else (phase_c.error_message or "phase_c_check_failed")
            latency_ms = phase_c.latency_ms
            details_json = {
                "scan_strategy": scan_strategy,
                "phase_a": {"skipped": True},
                "phase_b": {"skipped": True},
                "phase_c": asdict(phase_c),
                "score_explain": {
                    "total": score_total,
                    "factors": [
                        {
                            "name": "phase_c_success",
                            "value": phase_c.success,
                            "weight": 1.0,
                        }
                    ],
                },
            }
            jitter_ms: float | None = None
        else:
            phase_a = phase_a_dns_tcp(server.host, server.port, timeout_s=timeout_s)
            phase_b = phase_b_multi_tcp(server.host, server.port, timeout_s=timeout_s, attempts=attempts)

            score = explainable_score(
                success_rate=phase_b.success_rate,
                median_latency_ms=phase_b.rtt_median_ms,
                jitter_ms=phase_b.jitter_ms,
                last_error=phase_a.error_type,
            )

            # Business rule: check is "ok" only when phase A reaches host and
            # phase B has at least one successful probe.
            phase_b_has_success = phase_b.successes > 0 or phase_b.success_rate > 0.0
            status = "ok" if phase_a.success and phase_b_has_success else "fail"
            score_total = score.total

            if status == "ok":
                error_message = None
            elif not phase_a.success:
                error_message = phase_a.error_message
            else:
                error_message = "phase_b_has_no_successful_probes"

            latency_ms = phase_b.rtt_median_ms or phase_a.rtt_ms
            details_json = {
                "scan_strategy": scan_strategy,
                "phase_a": asdict(phase_a),
                "phase_b": asdict(phase_b),
                "phase_c": asdict(phase_c),
                "score_explain": asdict(score),
            }
            jitter_ms = phase_b.jitter_ms

        confidence_input = self._build_confidence_input(
            db,
            server.id,
            current_check_ok=status == "ok",
            jitter_ms=jitter_ms,
        )
        confidence = calculate_confidence(confidence_input)
        details_json["confidence"] = asdict(confidence)

        check = Check(
            server_id=server.id,
            status=status,
            latency_ms=latency_ms,
            error_message=error_message,
            details_json=details_json,
            score=score_total,
            confidence=confidence.confidence,
        )
        db.add(check)
        db.flush()

        self._update_daily_aggregate(db, check)
        db.commit()
        db.refresh(check)
        return check

    def _build_confidence_input(
        self,
        db: Session,
        server_id: int,
        current_check_ok: bool,
        jitter_ms: float | None,
    ) -> ConfidenceInput:
        previous_success = db.query(func.count(Check.id)).filter(Check.server_id == server_id, Check.status == "ok").scalar() or 0
        previous_total = db.query(func.count(Check.id)).filter(Check.server_id == server_id).scalar() or 0
        last_check = db.query(Check).filter(Check.server_id == server_id).order_by(Check.checked_at.desc()).first()

        return ConfidenceInput(
            success_count=previous_success + (1 if current_check_ok else 0),
            total_count=previous_total + 1,
            jitter_ms=jitter_ms,
            last_checked_at=normalize_utc_naive(last_check.checked_at) if last_check else None,
            now=normalize_utc_naive(datetime.now(timezone.utc)),
        )

    def _update_daily_aggregate(self, db: Session, check: Check) -> None:
        day = check.checked_at.date()
        aggregate = (
            db.query(DailyAggregate)
            .filter(DailyAggregate.server_id == check.server_id, DailyAggregate.day == day)
            .one_or_none()
        )

        if aggregate is None:
            aggregate = DailyAggregate(
                server_id=check.server_id,
                day=day,
                checks_total=1,
                success_total=1 if check.status == "ok" else 0,
                avg_latency_ms=check.latency_ms,
            )
            db.add(aggregate)
        else:
            previous_checks_total = aggregate.checks_total
            aggregate.checks_total += 1
            aggregate.success_total += 1 if check.status == "ok" else 0

            if check.latency_ms is not None:
                if aggregate.avg_latency_ms is None or previous_checks_total == 0:
                    aggregate.avg_latency_ms = check.latency_ms
                else:
                    aggregate.avg_latency_ms = aggregate.avg_latency_ms + (
                        check.latency_ms - aggregate.avg_latency_ms
                    ) / (previous_checks_total + 1)

    def recompute_daily_aggregate(self, db: Session, server_id: int, day: date) -> DailyAggregate:
        """Recovery-only full recomputation of daily aggregate from checks table."""
        aggregate = (
            db.query(DailyAggregate)
            .filter(DailyAggregate.server_id == server_id, DailyAggregate.day == day)
            .one_or_none()
        )
        checks = db.query(Check).filter(Check.server_id == server_id, func.date(Check.checked_at) == day).all()

        checks_total = len(checks)
        success_total = len([c for c in checks if c.status == "ok"])
        latencies = [c.latency_ms for c in checks if c.latency_ms is not None]
        avg_latency = (sum(latencies) / len(latencies)) if latencies else None

        if aggregate is None:
            aggregate = DailyAggregate(
                server_id=server_id,
                day=day,
                checks_total=checks_total,
                success_total=success_total,
                avg_latency_ms=avg_latency,
            )
            db.add(aggregate)
        else:
            aggregate.checks_total = checks_total
            aggregate.success_total = success_total
            aggregate.avg_latency_ms = avg_latency

        return aggregate
