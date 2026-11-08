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
from melorin.modules.vpn.targets import merge_config

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


def build_adapter(panel, server=None, *, credentials: dict | None = None) -> PanelAdapter:
    """Adapter for ``panel``. Pass ``server`` ONLY when creating a NEW account: its ``target`` (group/inbound set) is merged over
    the panel config. Renewals, suspends, deletes and health checks call it without a server and never touch the target."""
    if panel.kind == "mock" and not get_settings().allow_mock_providers:
        raise AppError("MOCK_PROVIDER_DISABLED", "Mock provisioning is disabled in this environment.", 503)
    if panel.kind != "upstream_bot" and get_settings().env in {"staging", "production"}:  # upstream_bot talks Telegram, not HTTP
        if not _public_panel_url(panel.base_url) or (panel.config or {}).get("verify_tls") is False:
            raise AppError("PANEL_TLS_VERIFY_REQUIRED", "Panel connections require HTTPS and certificate verification.", 503)
    try:
        cls = ADAPTERS[panel.kind]
    except KeyError as exc:
        raise AppError("PROVIDER_UNKNOWN", "VPN provider is not configured.", 400) from exc
    if credentials is not None:  # a transient credential (PG-05 bootstrap / verification): used for this adapter only, never stored
        creds = dict(credentials)
    else:
        creds = json.loads(decrypt(panel.credentials_enc) or "{}") if panel.credentials_enc else {}
    config = merge_config(panel.config, getattr(server, "target", None) if server is not None else None)
    return cls(base_url=panel.base_url, credentials=creds, config=config)


def register(kind: str, cls: type) -> None:
    """Extension point for new panels (Marzban, Hiddify, ...)."""
    ADAPTERS[kind] = cls


def seed_adapter(adapter, account):
    """Name-mapping adapters (upstream_bot) re-learn the upstream account name from VpnAccount.panel_ref. No-op for others."""
    remember = getattr(adapter, "remember", None)
    if callable(remember):
        snapshot = getattr(account, "delivery_snapshot", None) or {}  # R8: the link as it was delivered; the live link is the panel's
        remember(account.username, getattr(account, "panel_ref", None), snapshot.get("subscription_url"))
    return adapter
