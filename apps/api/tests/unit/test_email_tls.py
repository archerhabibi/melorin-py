"""SMTP over TLS must verify the server (audit INT-001).

``smtplib`` builds an *unverified* TLS context when it is given none (``ssl._create_stdlib_context``), so the SMTP password and
the message went to whoever answered on the wire. These tests talk to a real TLS listener on 127.0.0.1 that presents a
self-signed certificate: the client must refuse it unless the certificate is trusted *and* names the host it connected to.
"""

from __future__ import annotations

import datetime as dt
import socket
import ssl
import threading
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from melorin.core import email as email_mod

CRLF = bytes((13, 10))  # carriage return, line feed
END_OF_DATA = CRLF + b"." + CRLF


def _write_self_signed(directory: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.UTC)
    usage = x509.KeyUsage(
        digital_signature=True,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=True,
        crl_sign=False,
        encipher_only=False,
        decipher_only=False,
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(usage, critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / "smtp-cert.pem", directory / "smtp-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return cert_path, key_path


class _SmtpServer:
    """One-connection SMTP responder. ``ssl``: TLS from the first byte. ``starttls``: plain greeting, then STARTTLS."""

    def __init__(self, cert: Path, key: Path, mode: str) -> None:
        self._tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._tls.load_cert_chain(cert, key)
        self._mode = mode
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._listener.settimeout(10)
        self.port: int = self._listener.getsockname()[1]
        self.messages: list[bytes] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._listener.close()
        self._thread.join(timeout=5)

    @staticmethod
    def _line(conn: socket.socket) -> bytes:
        buf = b""
        while not buf.endswith(CRLF):
            chunk = conn.recv(1)
            if not chunk:
                break
            buf += chunk
        return buf

    def _serve(self) -> None:
        try:
            conn, _ = self._listener.accept()
            conn.settimeout(10)
            secured = self._mode == "ssl"
            if secured:
                conn = self._tls.wrap_socket(conn, server_side=True)
            conn.sendall(b"220 test ESMTP" + CRLF)
            while True:
                line = self._line(conn).upper()
                if not line or line.startswith(b"QUIT"):
                    conn.sendall(b"221 bye" + CRLF)
                    return
                if line.startswith((b"EHLO", b"HELO")):
                    offer = self._mode == "starttls" and not secured
                    conn.sendall((b"250-test" + CRLF + b"250 STARTTLS" if offer else b"250 test") + CRLF)
                elif line.startswith(b"STARTTLS"):
                    conn.sendall(b"220 go ahead" + CRLF)
                    conn = self._tls.wrap_socket(conn, server_side=True)
                    secured = True
                elif line.startswith(b"DATA"):
                    conn.sendall(b"354 go" + CRLF)
                    data = b""
                    while not data.endswith(END_OF_DATA):
                        chunk = conn.recv(4096)
                        if not chunk:
                            return
                        data += chunk
                    self.messages.append(data)
                    conn.sendall(b"250 queued" + CRLF)
                else:
                    conn.sendall(b"250 ok" + CRLF)
        except OSError:  # the client hung up, e.g. after refusing our certificate
            return


def _cfg(port: int, security: str, host: str = "localhost") -> dict:
    return {"host": host, "port": port, "username": "", "password": "", "from_addr": "noreply@example.test", "security": security}


def _trust(monkeypatch: pytest.MonkeyPatch, cert: Path) -> None:
    """Make the default verifying context trust exactly this certificate (stands in for an operator's CA bundle)."""
    real = ssl.create_default_context
    monkeypatch.setattr(ssl, "create_default_context", lambda *a, **k: real(cafile=str(cert)))


@pytest.fixture
def certs(tmp_path: Path) -> tuple[Path, Path]:
    return _write_self_signed(tmp_path)


@pytest.mark.parametrize("security", ["ssl", "starttls"])
def test_a_certificate_nobody_trusts_is_refused_and_nothing_is_sent(certs, security):
    server = _SmtpServer(*certs, security)
    try:
        with pytest.raises(ssl.SSLCertVerificationError):
            email_mod._smtp_send(_cfg(server.port, security), "u@example.test", "subject", "body")
    finally:
        server.close()
    assert server.messages == []


@pytest.mark.parametrize("security", ["ssl", "starttls"])
def test_a_trusted_certificate_for_the_right_host_delivers(certs, security, monkeypatch):
    _trust(monkeypatch, certs[0])
    server = _SmtpServer(*certs, security)
    try:
        email_mod._smtp_send(_cfg(server.port, security), "u@example.test", "the-subject", "the-body")
    finally:
        server.close()
    assert len(server.messages) == 1 and b"the-subject" in server.messages[0] and b"the-body" in server.messages[0]


@pytest.mark.parametrize("security", ["ssl", "starttls"])
def test_a_trusted_certificate_for_another_host_name_is_refused(certs, security, monkeypatch):
    _trust(monkeypatch, certs[0])
    server = _SmtpServer(*certs, security)
    try:
        with pytest.raises(ssl.SSLCertVerificationError):  # the certificate names only 'localhost'
            email_mod._smtp_send(_cfg(server.port, security, host="127.0.0.1"), "u@example.test", "subject", "body")
    finally:
        server.close()
    assert server.messages == []
