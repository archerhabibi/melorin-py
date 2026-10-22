"""Sanaei 3x-ui adapter (https://github.com/MHSanaei/3x-ui, API reference: https://docs.sanaei.dev/docs/reference/api/).

Two API generations are supported:

* ``v3`` (3x-ui 3.x): clients are first-class rows under ``/panel/api/clients/*`` and can be attached
  to several inbounds at once.
    - read:    GET  /panel/api/clients/get/{email}      -> obj = {"client": {...}, "inboundIds": [...]}
                    (not found = HTTP 200 + success=false + msg "record not found")
    - traffic: GET  /panel/api/clients/traffic/{email}  -> obj = {up, down, total, expiryTime, enable, ...}
    - links:   GET  /panel/api/clients/links/{email}    -> obj = ["vless://...", ...]
    - create:  POST /panel/api/clients/add              {"client": {...}, "inboundIds": [...]}
               (per-protocol secrets are generated server-side when omitted)
    - update:  POST /panel/api/clients/update/{email}   full row replace (NOT a patch): read -> merge -> write
    - delete:  POST /panel/api/clients/del/{email}
    - reset:   POST /panel/api/clients/resetTraffic/{email}
    - health:  GET  /panel/api/server/status
* ``legacy`` (3x-ui 1.x/2.x): clients live inside ``inbound.settings.clients``.
    - GET /panel/api/inbounds/get/{id}, POST /panel/api/inbounds/addClient,
      POST /panel/api/inbounds/updateClient/{clientId}, POST /panel/api/inbounds/{id}/delClient/{clientId},
      POST /panel/api/inbounds/{id}/resetClientTraffic/{email}, POST /server/status

``api_style="auto"`` (default) probes ``/panel/api/clients/*`` once and falls back to legacy on 404.

Auth: ``Authorization: Bearer <api_token>`` (Settings -> Security -> API Token; preferred, no session,
no CSRF) or cookie session from ``POST {base}/login``. The panel answers unauthenticated requests with
404 (401 when ``X-Requested-With: XMLHttpRequest`` is sent, which we always send), so a 401 means
"session expired" and a 404 means "route does not exist".

base_url must include the panel web base path (e.g. ``https://panel.example.com:2053/kharej``).
Redirects are never followed with credentials (credential forwarding / SSRF).

Panel.config:
  {"api_style": "auto" | "v3" | "legacy",
   "inbound_ids": [1, 2],                 # or legacy "inbound_id": 1
   "template_username": "template",       # optional: copy inboundIds/flow/limitIp from a manually-made client
   "sub_base_url": "https://sub.example.com:2096/sub",   # REQUIRED: Sub Port + Sub Path, subId is appended
   "flow": "",                            # e.g. "xtls-rprx-vision"
   "limit_ip": 0,                         # default device/IP limit when AccountSpec.max_devices is empty
   "fetch_links": true, "verify_tls": true, "timeout": 15}
Panel credentials (encrypted): {"api_token": "..."} or {"username": "...", "password": "..."}
"""

from melorin.modules.vpn.adapters.sanaei.adapter import SanaeiAdapter
from melorin.modules.vpn.adapters.sanaei.wire import clean_client, from_ms, to_ms

__all__ = ["SanaeiAdapter", "clean_client", "from_ms", "to_ms"]
