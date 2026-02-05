import pytest

from app.vless.parser import VlessParseError, parse_vless_uri


VALID_UUID = "c2f5df35-6ce4-4f72-8838-9d17f76a71f8"


def test_parse_valid_vless_uri() -> None:
    uri = (
        f"vless://{VALID_UUID}@example.com:443?security=tls&encryption=none&type=ws"
        "&sni=cdn.example.com&fp=chrome&alpn=h2&flow=xtls-rprx-vision"
        "&path=%2Fws&host=api.example.com&serviceName=svc"
        "&pbk=pub-key&sid=shortid&spx=spxv&mode=gun&headerType=http#My%20Server"
    )

    parsed = parse_vless_uri(uri)

    assert parsed.scheme == "vless"
    assert str(parsed.user_id) == VALID_UUID
    assert parsed.host == "example.com"
    assert parsed.port == 443
    assert parsed.name == "My Server"
    assert parsed.query.type == "ws"
    assert parsed.query.path == "/ws"
    assert parsed.server_aliases == [uri]
    assert parsed.original_uri == uri


@pytest.mark.parametrize(
    "uri,error",
    [
        ("http://example.com", "Unsupported scheme"),
        ("vless://not-a-uuid@example.com:443", "Invalid UUID"),
        (f"vless://{VALID_UUID}@", "Host is required"),
        (f"vless://{VALID_UUID}@example.com", "Port is required"),
    ],
)
def test_parse_invalid_base_components(uri: str, error: str) -> None:
    with pytest.raises(VlessParseError, match=error):
        parse_vless_uri(uri)


def test_parse_invalid_query_key() -> None:
    uri = f"vless://{VALID_UUID}@example.com:443?unknown=1"

    with pytest.raises(VlessParseError, match="Extra inputs are not permitted"):
        parse_vless_uri(uri)


def test_parse_query_keeps_last_value_and_blank_values() -> None:
    uri = f"vless://{VALID_UUID}@example.com:443?security=tls&security=reality&path="

    parsed = parse_vless_uri(uri)

    assert parsed.query.security == "reality"
    assert parsed.query.path == ""
