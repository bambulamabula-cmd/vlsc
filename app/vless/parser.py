from __future__ import annotations

from enum import Enum
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class VlessParseError(ValueError):
    """Raised when a VLESS URI cannot be parsed into a normalized model."""


class VlessTransport(str, Enum):
    TCP = "tcp"
    WS = "ws"
    GRPC = "grpc"
    HTTPUPGRADE = "httpupgrade"
    SPLITHTTP = "splithttp"
    XHTTP = "xhttp"
    KCP = "kcp"
    QUIC = "quic"


class VlessQueryParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    security: str | None = None
    encryption: str | None = None
    type: VlessTransport | None = None
    sni: str | None = None
    fp: str | None = None
    alpn: str | None = None
    flow: str | None = None
    path: str | None = None
    host: str | None = None
    serviceName: str | None = None
    pbk: str | None = None
    sid: str | None = None
    spx: str | None = None
    mode: str | None = None
    headerType: str | None = None


class VlessUri(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheme: str = Field(default="vless")
    user_id: UUID
    host: str
    port: int
    name: str | None = None
    query: VlessQueryParams = Field(default_factory=VlessQueryParams)
    original_uri: str
    server_aliases: list[str] = Field(default_factory=list)

    @field_validator("scheme")
    @classmethod
    def validate_scheme(cls, value: str) -> str:
        if value.lower() != "vless":
            raise ValueError("scheme must be vless")
        return value.lower()

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        host = value.strip()
        if not host:
            raise ValueError("host is required")
        return host

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("port must be in range 1..65535")
        return value


def _flatten_query_params(query_string: str) -> dict[str, str]:
    parsed = parse_qs(query_string, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def parse_vless_uri(uri: str) -> VlessUri:
    """Parse and validate a `vless://...` URI into a normalized typed model."""

    if not uri or not uri.strip():
        raise VlessParseError("URI is empty")

    split = urlsplit(uri.strip())
    if split.scheme.lower() != "vless":
        raise VlessParseError("Unsupported scheme; expected vless://")

    if split.username is None:
        raise VlessParseError("UUID (user info) is required")

    try:
        user_id = UUID(split.username)
    except (ValueError, AttributeError) as exc:
        raise VlessParseError("Invalid UUID in URI") from exc

    if not split.hostname:
        raise VlessParseError("Host is required")

    if split.port is None:
        raise VlessParseError("Port is required")

    name = unquote(split.fragment) if split.fragment else None
    query_map = _flatten_query_params(split.query)

    try:
        query = VlessQueryParams.model_validate(query_map)
        return VlessUri(
            scheme=split.scheme,
            user_id=user_id,
            host=split.hostname,
            port=split.port,
            name=name,
            query=query,
            original_uri=uri,
            server_aliases=[uri],
        )
    except ValidationError as exc:
        raise VlessParseError(str(exc)) from exc


def normalize_vless_uri(uri: str) -> dict[str, Any]:
    """Return normalized dict payload convenient for persistence layers."""

    parsed = parse_vless_uri(uri)
    return parsed.model_dump(mode="json")
