from __future__ import annotations

from app.checks.xray_adapter import PhaseCResult, XrayAdapter


class XrayPoolService:
    """Thin wrapper around Xray adapter with stable service-level API.

    Note: checks are executed synchronously in the caller thread.
    `max_workers` is preserved for backward compatibility.
    """

    def __init__(self, max_workers: int = 2) -> None:
        self.adapter = XrayAdapter(max_workers=max_workers)

    def check_http_via_xray(self, host: str, port: int, enabled: bool, timeout_s: float) -> PhaseCResult:
        return self.adapter.phase_c_http_check(host, port, timeout_s=timeout_s, enabled=enabled)
