"""Outgoing webhook primitives (doc 05/06 v1.1): HMAC signing, replay window, SSRF guard, backoff."""

import hashlib
import hmac
import ipaddress
import json
import time
from urllib.parse import urlsplit

SIGNATURE_HEADER = "X-Melorin-Signature"
EVENT_ID_HEADER = "X-Melorin-Event-Id"
EVENT_TYPE_HEADER = "X-Melorin-Event"
TIMESTAMP_HEADER = "X-Melorin-Timestamp"
DEFAULT_TOLERANCE = 300  # seconds
BACKOFF = (30, 120, 600, 1800, 3600, 7200, 21600, 43200)
MAX_ATTEMPTS = len(BACKOFF) + 1
SUPPORTED_EVENTS = (
    "order.completed",
    "order.refunded",
    "order.provisioning_failed",
    "payment.succeeded",
    "payment.failed",
    "wallet.changed",
    "vpn_account.expired",
    "vpn_account.near_expiry",
    "reseller.debt",
)


class WebhookUrlError(ValueError):
    pass


def canonical_body(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def verify(secret: str, header: str, body: bytes, *, now: int | None = None, tolerance: int = DEFAULT_TOLERANCE) -> bool:
    """Reference verifier for receivers (also used by tests)."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
        got = parts["v1"]
    except (ValueError, KeyError):
        return False
    now = int(time.time()) if now is None else now
    if abs(now - ts) > tolerance:
        return False
    expected = sign(secret, ts, body).split("v1=", 1)[1]
    return hmac.compare_digest(expected, got)


def next_delay(attempt: int) -> int | None:
    """attempt = number of failed attempts so far (1-based). None => give up."""
    if attempt < 1 or attempt > len(BACKOFF):
        return None
    return BACKOFF[attempt - 1]


def _blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
            getattr(ip, "is_site_local", False),
        )
    )


def check_url(url: str, *, allow_http: bool = False, resolved_ips: list[str] | None = None) -> str:
    """Static SSRF checks. resolved_ips (from DNS at delivery time) are checked too."""
    parts = urlsplit(url)
    if parts.scheme not in ("https",) + (("http",) if allow_http else ()):
        raise WebhookUrlError("only https endpoints are allowed")
    if not parts.hostname or parts.username or parts.password:
        raise WebhookUrlError("invalid host")
    host = parts.hostname.lower()
    if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
        raise WebhookUrlError("internal host")
    try:
        parsed_ip = ipaddress.ip_address(host)
    except ValueError:
        parsed_ip = None  # hostname, resolved below
    if parsed_ip is not None and _blocked_ip(parsed_ip):
        raise WebhookUrlError("private address")
    for raw in resolved_ips or []:
        if _blocked_ip(ipaddress.ip_address(raw)):
            raise WebhookUrlError("resolves to private address")
    if parts.port and parts.port not in (80, 443, 8080, 8443):
        raise WebhookUrlError("port not allowed")
    return url


def subscribed(endpoint_events: list[str] | None, event: str) -> bool:
    return not endpoint_events or "*" in endpoint_events or event in endpoint_events
