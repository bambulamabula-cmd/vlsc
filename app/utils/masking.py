from __future__ import annotations

import hashlib
from uuid import UUID


def hash_uuid(uuid_value: str | UUID, *, length: int = 12) -> str:
    """Return a stable, short SHA-256 based hash for UUID-like identifiers."""

    normalized = str(UUID(str(uuid_value))).lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:length]


def mask_uuid(uuid_value: str | UUID) -> str:
    """Mask UUID to keep only the first and last block for safe display/logging."""

    normalized = str(UUID(str(uuid_value))).lower()
    parts = normalized.split("-")
    return f"{parts[0]}-****-****-****-{parts[-1]}"
