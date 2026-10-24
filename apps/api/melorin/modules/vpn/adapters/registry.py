import json
import ipaddress
import socket
from urllib.parse import urlparse

from melorin.core.crypto import decrypt
from melorin.core.config import get_settings
from melorin.core.errors import AppError
from melorin.modules.vpn.adapters.base import PanelAdapter
from melorin.modules.vpn.adapters.mock import MockPanelAdapter
from melorin.modules.vpn.adapters.pasarguard import PasarGuardAdapter
from melorin.modules.vpn.adapters.sanaei import SanaeiAdapter
from melorin.modules.vpn.adapters.upstream_bot import UpstreamBotAdapter

ADAPTERS: dict[str, type] = {
    "sanaei": SanaeiAdapter,
    "pasarguard": PasarGuardAdapter,
    "mock": MockPanelAdapter,
    "upstream_bot": UpstreamBotAdapter,
}


def _public_panel_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror:
        return False
    return bool(addresses) and all(
        not (ip := ipaddress.ip_address(address)).is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_reserved
        and not ip.is_multicast
        for address in addresses
    )


def build_adapter(panel) -> PanelAdapter:
    if panel.kind == "mock" and not get_settings().allow_mock_providers:
        raise AppError("MOCK_PROVIDER_DISABLED", "Mock provisioning is disabled in this environment.", 503)
    if panel.kind != "upstream_bot" and get_settings().env in {"staging", "production"}:  # upstream_bot talks Telegram, not HTTP
        if not _public_panel_url(panel.base_url) or (panel.config or {}).get("verify_tls") is False:
            raise AppError("PANEL_TLS_VERIFY_REQUIRED", "Panel connections require HTTPS and certificate verification.", 503)
    try:
        cls = ADAPTERS[panel.kind]
    except KeyError as exc:
        raise AppError("PROVIDER_UNKNOWN", "VPN provider is not configured.", 400) from exc
    creds = json.loads(decrypt(panel.credentials_enc) or "{}") if panel.credentials_enc else {}
    return cls(base_url=panel.base_url, credentials=creds, config=panel.config or {})


def register(kind: str, cls: type) -> None:
    """Extension point for new panels (Marzban, Hiddify, ...)."""
    ADAPTERS[kind] = cls


def seed_adapter(adapter, account):
    """Name-mapping adapters (upstream_bot) re-learn the upstream account name from VpnAccount.panel_ref. No-op for others."""
    remember = getattr(adapter, "remember", None)
    if callable(remember):
        remember(account.username, getattr(account, "panel_ref", None), getattr(account, "subscription_url", None))
    return adapter
