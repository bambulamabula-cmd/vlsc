from __future__ import annotations

import json
import shutil
import socket
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib import request


@dataclass(frozen=True)
class PhaseCResult:
    enabled: bool
    available: bool
    success: bool
    latency_ms: float | None
    error_message: str | None


class XrayAdapter:
    def __init__(self, max_workers: int = 2) -> None:
        self.xray_path = shutil.which("xray")
        self.pool = ThreadPoolExecutor(max_workers=max(1, min(max_workers, 2)), thread_name_prefix="xray-check")

    @property
    def available(self) -> bool:
        return self.xray_path is not None

    def phase_c_http_check(
        self,
        target_host: str,
        target_port: int,
        timeout_s: float = 8.0,
        enabled: bool = True,
    ) -> PhaseCResult:
        if not enabled:
            return PhaseCResult(enabled=False, available=self.available, success=False, latency_ms=None, error_message=None)

        if not self.available:
            return PhaseCResult(
                enabled=True,
                available=False,
                success=False,
                latency_ms=None,
                error_message="xray binary is not available",
            )

        return self._run_xray_check(target_host, target_port, timeout_s)

    def _run_xray_check(self, target_host: str, target_port: int, timeout_s: float) -> PhaseCResult:
        inbound_port = self._free_port()
        config = {
            "inbounds": [
                {
                    "tag": "local-http",
                    "listen": "127.0.0.1",
                    "port": inbound_port,
                    "protocol": "http",
                    "settings": {},
                }
            ],
            "outbounds": [
                {
                    "tag": "probe-out",
                    "protocol": "freedom",
                    "settings": {},
                }
            ],
            "routing": {
                "rules": [
                    {
                        "type": "field",
                        "outboundTag": "probe-out",
                        "domain": [f"full:{target_host}"],
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory(prefix="vlsc-xray-") as temp_dir:
            cfg_path = Path(temp_dir) / "config.json"
            cfg_path.write_text(json.dumps(config), encoding="utf-8")

            proc = subprocess.Popen(
                [self.xray_path, "run", "-c", str(cfg_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            started = time.perf_counter()
            try:
                time.sleep(0.5)
                req = request.Request(f"http://{target_host}:{target_port}/")
                opener = request.build_opener(
                    request.ProxyHandler({"http": f"http://127.0.0.1:{inbound_port}", "https": f"http://127.0.0.1:{inbound_port}"})
                )
                with opener.open(req, timeout=timeout_s):
                    pass
                latency_ms = (time.perf_counter() - started) * 1000
                return PhaseCResult(enabled=True, available=True, success=True, latency_ms=latency_ms, error_message=None)
            except Exception as exc:
                return PhaseCResult(
                    enabled=True,
                    available=True,
                    success=False,
                    latency_ms=None,
                    error_message=str(exc),
                )
            finally:
                self._terminate_strict(proc, timeout_s)

    @staticmethod
    def _terminate_strict(proc: subprocess.Popen[bytes], timeout_s: float) -> None:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=max(0.5, min(timeout_s, 3.0)))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1.0)

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])
