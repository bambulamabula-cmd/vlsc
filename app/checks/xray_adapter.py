from __future__ import annotations

import json
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
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
        # Keep `max_workers` in signature for backwards compatibility of public API.
        self.max_workers = max(1, min(max_workers, 2))

    @property
    def available(self) -> bool:
        return self.xray_path is not None

    def phase_c_http_check(
        self,
        target_host: str,
        target_port: int,
        vless_config: dict[str, Any] | None = None,
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

        try:
            normalized_vless = self._normalize_vless_config(vless_config)
        except ValueError as exc:
            return PhaseCResult(
                enabled=True,
                available=True,
                success=False,
                latency_ms=None,
                error_message=f"phase_c_vless_config_error: {exc}",
            )

        return self._run_xray_check(target_host, target_port, normalized_vless, timeout_s)

    def _run_xray_check(
        self,
        target_host: str,
        target_port: int,
        vless_config: dict[str, Any],
        timeout_s: float,
    ) -> PhaseCResult:
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
                    "protocol": "vless",
                    "settings": {
                        "vnext": [
                            {
                                "address": vless_config["host"],
                                "port": vless_config["port"],
                                "users": [
                                    {
                                        "id": vless_config["id"],
                                        "encryption": "none",
                                        **({"flow": vless_config["flow"]} if vless_config.get("flow") else {}),
                                    }
                                ],
                            }
                        ]
                    },
                    "streamSettings": self._build_stream_settings(vless_config),
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
    def _normalize_vless_config(vless_config: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(vless_config, dict):
            raise ValueError("Server.metadata_json is missing")

        query = vless_config.get("query")
        if not isinstance(query, dict):
            query = {}

        normalized = {
            "host": vless_config.get("host"),
            "port": vless_config.get("port"),
            "id": vless_config.get("id") or vless_config.get("uuid") or vless_config.get("user_id"),
            "security": query.get("security") or vless_config.get("security") or "none",
            "network": query.get("type") or vless_config.get("network") or vless_config.get("type") or "tcp",
            "sni": query.get("sni") or query.get("serverName") or vless_config.get("sni") or vless_config.get("serverName"),
            "fp": query.get("fp") or vless_config.get("fp"),
            "flow": query.get("flow") or vless_config.get("flow"),
            "ws_path": query.get("path") or vless_config.get("path"),
            "ws_host": query.get("host") or vless_config.get("ws_host") or vless_config.get("host_header"),
            "grpc_service_name": query.get("serviceName") or vless_config.get("serviceName"),
        }

        missing = [key for key in ("host", "port", "id") if not normalized.get(key)]

        if normalized.get("security") != "none":
            for key in ("sni", "fp"):
                if not normalized.get(key):
                    missing.append(key)

        if normalized.get("network") == "ws" and not normalized.get("ws_path"):
            missing.append("path")
        if normalized.get("network") == "grpc" and not normalized.get("grpc_service_name"):
            missing.append("serviceName")

        if missing:
            missing_fields = ", ".join(sorted(set(missing)))
            raise ValueError(f"required VLESS fields are missing: {missing_fields}")

        try:
            normalized["port"] = int(normalized["port"])
        except (TypeError, ValueError) as exc:
            raise ValueError("port must be an integer") from exc

        return normalized

    @staticmethod
    def _build_stream_settings(vless_config: dict[str, Any]) -> dict[str, Any]:
        security = str(vless_config["security"])
        sni = str(vless_config["sni"])
        fp = str(vless_config["fp"])
        network = str(vless_config["network"])

        stream_settings: dict[str, Any] = {
            "security": security,
            "network": network,
        }

        if security == "reality":
            stream_settings["realitySettings"] = {"serverName": sni, "fingerprint": fp}
        elif security != "none":
            stream_settings["tlsSettings"] = {"serverName": sni, "fingerprint": fp}

        if network == "ws":
            ws_settings: dict[str, Any] = {"path": vless_config["ws_path"]}
            if vless_config.get("ws_host"):
                ws_settings["headers"] = {"Host": vless_config["ws_host"]}
            stream_settings["wsSettings"] = ws_settings
        elif network == "grpc":
            stream_settings["grpcSettings"] = {"serviceName": vless_config["grpc_service_name"]}

        return stream_settings

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
