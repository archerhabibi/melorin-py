import json
from urllib.parse import urlparse

from melorin.core.crypto import decrypt
from melorin.core.config import get_settings
from melorin.core.errors import AppError
from melorin.modules.vpn.adapters.base import PanelAdapter
from melorin.modules.vpn.adapters.mock import MockPanelAdapter
from melorin.modules.vpn.adapters.pasarguard import PasarGuardAdapter
from melorin.modules.vpn.adapters.sanaei import SanaeiAdapter

ADAPTERS: dict[str, type] = {"sanaei": SanaeiAdapter, "pasarguard": PasarGuardAdapter, "mock": MockPanelAdapter}


def build_adapter(panel) -> PanelAdapter:
    if panel.kind == "mock" and not get_settings().allow_mock_providers:
        raise AppError("MOCK_PROVIDER_DISABLED", "Mock provisioning is disabled in this environment.", 503)
    if get_settings().env in {"staging", "production"}:
        if urlparse(panel.base_url).scheme != "https" or (panel.config or {}).get("verify_tls") is False:
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
