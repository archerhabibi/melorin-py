"""Sanaei wire format: error classification, millisecond timestamps and client-record normalisation (pure helpers)."""

import datetime as dt
import json


from melorin.modules.vpn.adapters.base import ErrorKind, PanelError

NOT_FOUND_MARKERS = ("record not found", "not found", "client not found", "no such client")

TEMPLATE_TTL = 300

CLIENT_FIELDS = (
    "id",
    "password",
    "auth",
    "security",
    "flow",
    "email",
    "limitIp",
    "limitHwid",
    "totalGB",
    "expiryTime",
    "enable",
    "tgId",
    "subId",
    "comment",
    "reset",
    "reverse",
    "group",
    "groupId",
)


def classify(status: int) -> ErrorKind:
    if status >= 500 or status in (408, 425, 429):
        return ErrorKind.TRANSIENT
    return ErrorKind.PERMANENT


def is_not_found(data: dict) -> bool:
    msg = str(data.get("msg") or "").lower()
    return data.get("success") is False and not data.get("obj") and any(m in msg for m in NOT_FOUND_MARKERS)


def to_ms(at: dt.datetime | None) -> int:
    if not at:
        return 0
    at = at if at.tzinfo else at.replace(tzinfo=dt.UTC)
    return int(at.timestamp() * 1000)


def from_ms(v) -> dt.datetime | None:
    try:
        v = int(v or 0)
    except (TypeError, ValueError):
        return None
    # Negative expiryTime = "starts on first use" (delayed start); no absolute date yet.
    return dt.datetime.fromtimestamp(v / 1000, dt.UTC) if v > 0 else None


def as_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def parse_settings(inbound: dict) -> dict:
    """3x-ui 3.x returns settings as a nested object, 2.x as a JSON-encoded string."""
    raw = inbound.get("settings")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except ValueError as e:
            raise PanelError(ErrorKind.PERMANENT, f"sanaei: inbound settings is not valid JSON: {e}") from e
    return {}


def clean_client(rec: dict) -> dict:
    """Turn a v3 ClientRecord (numeric id + uuid) into a model.Client payload (id = uuid string)."""
    out = {k: rec[k] for k in CLIENT_FIELDS if k in rec and k != "id"}
    rid = rec.get("uuid") or (rec.get("id") if isinstance(rec.get("id"), str) else None)
    if rid:
        out["id"] = rid
    # model.Client.tgId is int64: sending "" fails with "cannot unmarshal string ... tgId of type int64".
    out["tgId"] = as_int(rec.get("tgId"), 0)
    return out
