from __future__ import annotations

import math
import socket
import time
from dataclasses import dataclass
from statistics import median
from threading import Lock
from typing import Literal

ErrorType = Literal["dns_fail", "conn_refused", "timeout", "unknown"]


@dataclass(frozen=True)
class TcpAttempt:
    success: bool
    rtt_ms: float | None
    error_type: ErrorType | None


@dataclass(frozen=True)
class PhaseAResult:
    success: bool
    dns_ok: bool
    ip: str | None
    rtt_ms: float | None
    error_type: ErrorType | None
    error_message: str | None


@dataclass(frozen=True)
class PhaseBResult:
    attempts: int
    successes: int
    success_rate: float
    rtt_min_ms: float | None
    rtt_median_ms: float | None
    rtt_max_ms: float | None
    jitter_ms: float | None
    stopped_early: bool
    samples: tuple[TcpAttempt, ...]


class HostCooldown:
    def __init__(self) -> None:
        self._cooldown_until: dict[str, float] = {}
        self._lock = Lock()

    def in_cooldown(self, host: str) -> bool:
        now = time.monotonic()
        with self._lock:
            until = self._cooldown_until.get(host, 0.0)
            if until <= now:
                self._cooldown_until.pop(host, None)
                return False
            return True

    def set_cooldown(self, host: str, seconds: float) -> None:
        with self._lock:
            self._cooldown_until[host] = time.monotonic() + max(0.0, seconds)


HOST_COOLDOWN = HostCooldown()


def classify_error(exc: BaseException) -> ErrorType:
    if isinstance(exc, socket.gaierror):
        return "dns_fail"
    if isinstance(exc, ConnectionRefusedError):
        return "conn_refused"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in {110, 60}:
        return "timeout"
    return "unknown"


def tcp_probe(host: str, port: int, timeout_s: float) -> TcpAttempt:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            pass
        rtt_ms = (time.perf_counter() - started) * 1000
        return TcpAttempt(success=True, rtt_ms=rtt_ms, error_type=None)
    except BaseException as exc:
        return TcpAttempt(success=False, rtt_ms=None, error_type=classify_error(exc))


def phase_a_dns_tcp(host: str, port: int, timeout_s: float) -> PhaseAResult:
    try:
        dns_entries = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except BaseException as exc:
        return PhaseAResult(
            success=False,
            dns_ok=False,
            ip=None,
            rtt_ms=None,
            error_type=classify_error(exc),
            error_message=str(exc),
        )

    ip = dns_entries[0][4][0] if dns_entries else None
    attempt = tcp_probe(host, port, timeout_s)
    return PhaseAResult(
        success=attempt.success,
        dns_ok=True,
        ip=ip,
        rtt_ms=attempt.rtt_ms,
        error_type=attempt.error_type,
        error_message=None if attempt.success else (attempt.error_type or "unknown"),
    )


def phase_b_multi_tcp(
    host: str,
    port: int,
    timeout_s: float,
    attempts: int = 5,
    adaptive_stop_success_streak: int = 3,
    adaptive_stop_failure_streak: int = 3,
    backoff_base_s: float = 0.1,
    host_cooldown_s: float = 30.0,
) -> PhaseBResult:
    if HOST_COOLDOWN.in_cooldown(host):
        return PhaseBResult(
            attempts=0,
            successes=0,
            success_rate=0.0,
            rtt_min_ms=None,
            rtt_median_ms=None,
            rtt_max_ms=None,
            jitter_ms=None,
            stopped_early=True,
            samples=tuple(),
        )

    samples: list[TcpAttempt] = []
    success_streak = 0
    failure_streak = 0
    stopped_early = False

    for idx in range(max(1, attempts)):
        result = tcp_probe(host, port, timeout_s)
        samples.append(result)

        if result.success:
            success_streak += 1
            failure_streak = 0
        else:
            failure_streak += 1
            success_streak = 0
            delay = backoff_base_s * math.pow(2, failure_streak - 1)
            time.sleep(min(delay, 2.0))

        remaining = attempts - (idx + 1)
        if success_streak >= adaptive_stop_success_streak and remaining > 0:
            stopped_early = True
            break
        if failure_streak >= adaptive_stop_failure_streak and remaining > 0:
            stopped_early = True
            break

    success_rtts = [sample.rtt_ms for sample in samples if sample.success and sample.rtt_ms is not None]
    successes = len(success_rtts)
    total = len(samples)

    if successes == 0:
        HOST_COOLDOWN.set_cooldown(host, host_cooldown_s)

    jitter = None
    if len(success_rtts) >= 2:
        deltas = [abs(success_rtts[i] - success_rtts[i - 1]) for i in range(1, len(success_rtts))]
        jitter = sum(deltas) / len(deltas)

    return PhaseBResult(
        attempts=total,
        successes=successes,
        success_rate=(successes / total) if total else 0.0,
        rtt_min_ms=min(success_rtts) if success_rtts else None,
        rtt_median_ms=median(success_rtts) if success_rtts else None,
        rtt_max_ms=max(success_rtts) if success_rtts else None,
        jitter_ms=jitter,
        stopped_early=stopped_early,
        samples=tuple(samples),
    )
