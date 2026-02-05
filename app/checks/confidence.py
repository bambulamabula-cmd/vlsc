from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ConfidenceInput:
    success_count: int
    total_count: int
    jitter_ms: float | None
    last_checked_at: datetime | None
    now: datetime


@dataclass(frozen=True)
class ConfidenceResult:
    confidence: float
    components: dict[str, float]


def calculate_confidence(metrics: ConfidenceInput, half_life_hours: float = 24.0) -> ConfidenceResult:
    if metrics.total_count <= 0:
        return ConfidenceResult(confidence=0.0, components={"volume": 0.0, "stability": 0.0, "recency": 0.0})

    success_ratio = metrics.success_count / metrics.total_count
    volume = min(1.0, math.log1p(metrics.total_count) / math.log(11))

    if metrics.jitter_ms is None:
        stability = 0.5
    else:
        stability = max(0.0, 1.0 - min(metrics.jitter_ms, 200.0) / 200.0)

    if metrics.last_checked_at is None:
        recency = 0.0
    else:
        age_h = max(0.0, (metrics.now - metrics.last_checked_at).total_seconds() / 3600)
        recency = 0.5 ** (age_h / max(half_life_hours, 0.01))

    confidence = max(0.0, min(1.0, (0.5 * success_ratio + 0.25 * volume + 0.15 * stability + 0.10 * recency)))
    return ConfidenceResult(
        confidence=confidence,
        components={
            "success_ratio": success_ratio,
            "volume": volume,
            "stability": stability,
            "recency": recency,
        },
    )
