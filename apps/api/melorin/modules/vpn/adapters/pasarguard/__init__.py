"""PasarGuard panel adapter (https://github.com/PasarGuard/panel).

Package layout (PG-00): ``core`` transport/auth, ``users`` account lifecycle + usage + devices, ``admins`` store operators,
``nodes`` groups/templates/nodes/settings, ``ops`` Phase 4 (insight, infra control, bulk actions, admin governance, subscription probe), ``events`` webhook intake (verify, parse) and connect/disconnect at the panel, ``capabilities`` declared vs permitted capabilities.

API contract aligned with the production client in PGClockBot (app/services/pasarguard.py)
and the current PasarGuard panel API:
- auth:    POST /api/admin/token (form, grant_type=password) -> {"access_token": ...}; Bearer afterwards
- read:    GET  /api/user/by-username/{username}
- create:  POST /api/user   {username, status, group_ids, proxy_settings, data_limit, expire, hwid_limit, note}
- template create: POST /api/user/from_template {user_template_id, username, note}
- modify:  PUT  /api/user/by-id/{id}
- delete:  DELETE /api/user/by-id/{id}
- reset:   POST /api/user/by-id/{id}/reset          (traffic reset)
- rotate:  POST /api/user/by-id/{id}/revoke_sub     (new subscription link)
- owner:   PUT  /api/user/by-id/{id}/set_owner?admin_username=   (the account belongs to the store's admin)
- admins:  GET /api/admins?username=, POST /api/admin, PUT /api/admin/by-id/{id}, GET /api/admin-roles/simple
- health:  GET  /api/system  (fallback GET /api/admin, which needs no admins.read)
`expire` is sent as ISO-8601 UTC ("...Z"), 0 = never. `data_limit` bytes, 0 = unlimited.
Redirects are never followed with a Bearer token (credential forwarding / SSRF).

Panel.config (the destination keys below may also come from ``Server.target``, which wins; see vpn.targets):
  {"group_ids": [1, 2],            # REQUIRED by current PasarGuard UserCreate (or "user_template_id" instead)
   "limits_from": "product"|"template",  # template mode only: product (default) re-applies the package volume/time after creation
   "api_style": "current"|"legacy", # legacy = Marzban-style /api/user/{username} (old PasarGuard builds)
   "sub_base_url": "https://sub.example.com",  # prefix for relative subscription_url
   "verify_tls": true, "timeout": 20, "username_prefix": ""}
Panel credentials (encrypted): {"username": "...", "password": "..."},
{"access_token": "..."} or {"api_key": "..."}.
"""

from melorin.modules.vpn.adapters.pasarguard.access import AccessMixin
from melorin.modules.vpn.adapters.pasarguard.admins import AdminsMixin
from melorin.modules.vpn.adapters.pasarguard.capabilities import CapabilitiesMixin
from melorin.modules.vpn.adapters.pasarguard.events import EventsMixin
from melorin.modules.vpn.adapters.pasarguard.core import (  # noqa: F401  (re-exported: tests and callers import these from here)
    _TOKEN_TTL,
    _TOKENS,
    PasarGuardCore,
    _classify,
    _error_detail,
    iso_expire,
    parse_expire,
    time,
)
from melorin.modules.vpn.adapters.pasarguard.nodes import NodesMixin
from melorin.modules.vpn.adapters.pasarguard.ops import OpsMixin
from melorin.modules.vpn.adapters.pasarguard.users import _STATUS, UsersMixin, build_create_payload, build_modify_payload  # noqa: F401


class PasarGuardAdapter(UsersMixin, AdminsMixin, AccessMixin, NodesMixin, OpsMixin, EventsMixin, CapabilitiesMixin, PasarGuardCore):
    """PanelAdapter + the optional operation groups (NodeOps, UsageOps, DeviceOps, BulkOps, AdminOps, SettingsOps).

    Which of them a connection may use is ``capabilities()`` (declared) narrowed by ``discover_capabilities()`` (permitted)."""

    kind = "pasarguard"


__all__ = ["PasarGuardAdapter", "build_create_payload", "build_modify_payload", "iso_expire", "parse_expire"]
