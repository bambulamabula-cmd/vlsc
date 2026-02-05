from __future__ import annotations

import hashlib


def fingerprint_value(value: str) -> str:
    """Generate deterministic fingerprint for deduplication tasks."""

    normalized = value.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
