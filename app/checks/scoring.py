from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ErrorType = Literal["dns_fail", "conn_refused", "timeout", "unknown"]

ERROR_PENALTIES: dict[ErrorType, int] = {
    "dns_fail": 45,
    "conn_refused": 30,
    "timeout": 35,
    "unknown": 20,
}


@dataclass(frozen=True)
class ScoreExplain:
    total: int
    availability_component: int
    latency_component: int
    stability_component: int
    error_penalty: int
    factors: dict[str, float | int | str]


def _latency_points(latency_ms: float | None) -> int:
    if latency_ms is None:
        return 0
    if latency_ms <= 60:
        return 30
    if latency_ms <= 120:
        return 24
    if latency_ms <= 250:
        return 16
    if latency_ms <= 500:
        return 8
    return 2


def explainable_score(
    success_rate: float,
    median_latency_ms: float | None,
    jitter_ms: float | None,
    last_error: ErrorType | None,
) -> ScoreExplain:
    availability_component = round(max(0.0, min(1.0, success_rate)) * 50)
    latency_component = _latency_points(median_latency_ms)

    if jitter_ms is None:
        stability_component = 10 if success_rate > 0 else 0
    else:
        stability_component = max(0, 20 - round(min(jitter_ms, 200.0) / 10))

    error_penalty = ERROR_PENALTIES.get(last_error, 0) if last_error else 0
    total = max(0, min(100, availability_component + latency_component + stability_component - error_penalty))

    return ScoreExplain(
        total=total,
        availability_component=availability_component,
        latency_component=latency_component,
        stability_component=stability_component,
        error_penalty=error_penalty,
        factors={
            "success_rate": success_rate,
            "median_latency_ms": median_latency_ms if median_latency_ms is not None else "n/a",
            "jitter_ms": jitter_ms if jitter_ms is not None else "n/a",
            "last_error": last_error or "none",
        },
    )
