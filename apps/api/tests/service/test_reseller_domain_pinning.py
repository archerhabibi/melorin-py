"""Domain-proof connections must use an address that passed the public-network policy."""

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

from melorin.modules.reseller import auto_verify


@pytest.mark.parametrize(
    ("address", "family", "sockaddr"),
    [
        ("93.184.216.34", socket.AF_INET, ("93.184.216.34", 0)),
        ("2606:4700:4700::1111", socket.AF_INET6, ("2606:4700:4700::1111", 0, 0, 0)),
    ],
)
async def test_domain_proof_connects_to_the_checked_address(monkeypatch, address, family, sockaddr):
    requests, lookups = [], []

    async def resolve(host, port, **kwargs):
        lookups.append(host)
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]

    def handle(request):
        requests.append(request)
        return httpx.Response(200, text="proof")

    def client(purpose, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handle)
        kwargs["trust_env"] = False
        return httpx.AsyncClient(**kwargs)

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(auto_verify, "outbound_client", client)
    assert await auto_verify.check_http("shop.example.com", "proof") is True
    assert lookups == ["shop.example.com"]
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == address
    assert request.url.path == "/.well-known/melorin-verify.txt"
    assert request.headers["host"] == "shop.example.com"
    assert request.extensions["sni_hostname"] == "shop.example.com"


async def test_domain_proof_refuses_mixed_public_and_private_answers(monkeypatch):
    async def resolve(host, port, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.1.2.3", 0)),
        ]

    def unexpected_client(*args, **kwargs):
        pytest.fail("a refused endpoint must not receive a connection")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(auto_verify, "outbound_client", unexpected_client)
    assert await auto_verify.check_http("shop.example.com", "proof") is False


def _certificate(tmp_path: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "shop.example.com")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("shop.example.com")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "domain-cert.pem", tmp_path / "domain-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return cert_path, key_path


@pytest.mark.parametrize(("host", "allowed"), [("shop.example.com", True), ("wrong.example.com", False)])
async def test_domain_proof_preserves_tls_hostname_verification(tmp_path, monkeypatch, host, allowed):
    cert, key = _certificate(tmp_path)
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.load_cert_chain(cert, key)
    server_names, requests = [], []
    server_tls.set_servername_callback(lambda sock, name, ctx: server_names.append(name))

    async def respond(reader, writer):
        try:
            requests.append(await reader.readuntil(b"\r\n\r\n"))
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nproof")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(respond, "127.0.0.1", 0, ssl=server_tls)
    port = server.sockets[0].getsockname()[1]
    client_tls = ssl.create_default_context(cafile=str(cert))

    async def checked_address(domain):
        return "127.0.0.1"  # local listener after the public-address policy step

    class LocalPortTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.AsyncHTTPTransport(verify=client_tls, trust_env=False)

        async def handle_async_request(self, request):
            request.url = request.url.copy_with(port=port)
            return await self.inner.handle_async_request(request)

        async def aclose(self):
            await self.inner.aclose()

    def client(purpose, **kwargs):
        kwargs["transport"] = LocalPortTransport()
        kwargs["trust_env"] = False
        return httpx.AsyncClient(**kwargs)

    monkeypatch.setattr(auto_verify, "resolve_public_address", checked_address, raising=False)
    monkeypatch.setattr(auto_verify, "outbound_client", client)
    try:
        assert await auto_verify.check_http(host, "proof") is allowed
        assert server_names == [host]
        if allowed:
            assert len(requests) == 1
            assert f"host: {host}".encode() in requests[0].lower()
        else:
            assert requests == []
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize("domain", ["", "shop.example.com:8443", "user@shop.example.com", "shop.example.com/path", "shop.example.com?x=1"])
async def test_domain_proof_rejects_non_hostnames_before_resolving(monkeypatch, domain):
    async def unexpected_resolve(host, port, **kwargs):
        pytest.fail("invalid domains must not be resolved")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", unexpected_resolve)
    assert await auto_verify.check_http(domain, "proof") is False
