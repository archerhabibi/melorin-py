"""The OCR connection must use the address checked by its SSRF policy."""

from __future__ import annotations

import asyncio
import datetime as dt
import socket
import ssl
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from melorin.modules.payments import receipt_ocr


def _config(base_url: str) -> receipt_ocr.OcrConfig:
    return receipt_ocr.OcrConfig("vision", "test-key", base_url, "test-model", 3, "fas")


@pytest.mark.parametrize(
    ("address", "family", "sockaddr"),
    [
        ("93.184.216.34", socket.AF_INET, ("93.184.216.34", 0)),
        ("2606:4700:4700::1111", socket.AF_INET6, ("2606:4700:4700::1111", 0, 0, 0)),
    ],
)
async def test_vision_connects_to_the_checked_address(monkeypatch, address, family, sockaddr):
    lookups = []
    requests = []

    async def resolve(host, port, **kwargs):
        lookups.append(host)
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"content": []})

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(
        receipt_ocr,
        "outbound_client",
        lambda purpose, **kw: httpx.AsyncClient(transport=httpx.MockTransport(handle), trust_env=False, **kw),
    )
    response = await receipt_ocr.post_vision(_config("https://ocr.example:8443/prefix"), b"test image", "image/png", "read", max_tokens=3)
    assert response.status_code == 200
    assert lookups == ["ocr.example"]
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == address
    assert request.url.port == 8443
    assert request.url.path == "/prefix/v1/messages"
    assert request.headers["host"] == "ocr.example:8443"
    assert request.headers["x-api-key"] == "test-key"
    assert request.extensions["sni_hostname"] == "ocr.example"


async def test_vision_refuses_a_mixed_public_and_private_dns_answer(monkeypatch):
    async def resolve(host, port, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.1.2.3", 0)),
        ]

    def unexpected_client(*args, **kwargs):
        pytest.fail("a refused endpoint must not receive a connection")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(receipt_ocr, "outbound_client", unexpected_client)
    with pytest.raises(receipt_ocr.OcrEndpointForbidden):
        await receipt_ocr.post_vision(_config("https://ocr.example"), b"test image", "image/png", "read", max_tokens=3)


def _certificate(tmp_path: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ocr.example")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("ocr.example")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "ocr-cert.pem", tmp_path / "ocr-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return cert_path, key_path


@pytest.mark.parametrize(("host", "allowed"), [("ocr.example", True), ("wrong.example", False)])
async def test_vision_keeps_tls_host_verification_when_connecting_to_an_ip(tmp_path, monkeypatch, host, allowed):
    cert, key = _certificate(tmp_path)
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.load_cert_chain(cert, key)
    server_names = []
    server_tls.set_servername_callback(lambda sock, name, ctx: server_names.append(name))
    requests = []

    async def respond(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            length = next(int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n") if line.lower().startswith(b"content-length:"))
            body = await reader.readexactly(length)
            requests.append((headers, body))
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(respond, "127.0.0.1", 0, ssl=server_tls)
    port = server.sockets[0].getsockname()[1]
    client_tls = ssl.create_default_context(cafile=str(cert))

    async def checked_address(url):
        return "127.0.0.1"  # this test uses a local listener after the policy step

    monkeypatch.setattr(receipt_ocr, "assert_public_endpoint", checked_address)
    monkeypatch.setattr(
        receipt_ocr,
        "outbound_client",
        lambda purpose, **kw: httpx.AsyncClient(verify=client_tls, trust_env=False, **kw),
    )
    try:
        config = _config(f"https://{host}:{port}/prefix")
        if allowed:
            response = await receipt_ocr.post_vision(config, b"test image", "image/png", "read", max_tokens=3)
            assert response.status_code == 200
        else:
            with pytest.raises(httpx.ConnectError):
                await receipt_ocr.post_vision(config, b"test image", "image/png", "read", max_tokens=3)
        assert server_names == [host]
        if allowed:
            assert len(requests) == 1
            assert f"host: {host}:{port}".encode() in requests[0][0].lower()
            assert b"test-key" in requests[0][0]
        else:
            assert requests == []
    finally:
        server.close()
        await server.wait_closed()
