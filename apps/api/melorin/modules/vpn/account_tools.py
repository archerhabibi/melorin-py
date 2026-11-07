"""Account tools (PG-10): usage, last seen, devices, link rotation, suspend/resume and compensation for ONE account.

Every channel (customer bot/site, reseller bot/site, admin) goes through this module, so the rules are written once:

* **Who may do what** is the ``TOOLS`` table (role x tool). A role that is not listed never reaches the panel.
* **What the panel can do** is ``capabilities_of(panel)`` (the stored permission probe, else the static declaration): a tool the
  panel or its credential cannot serve is reported as unavailable with a reason, never attempted.
* **Scope is the caller's job.** The router resolves the account through ``StoreScope`` (customer), ``reseller_find`` (store
  owner) or the admin session and hands the row in; this module never widens it.
* **Privacy.** Connection IPs are never exposed here. "Last seen" is the synced ``online_at``; device ids (HWID) are the
  customer's own devices and are only returned for the account the caller already reached.
* **Writes are audited** with the acting role. Suspend/resume/compensation are owner/admin only. Compensation is admin only,
  needs a reason and is computed from a FRESH panel read (absolute values), so a retried call after a timeout can be re-read
  and compared instead of silently adding twice.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.domain.order_state import VpnStatus
from melorin.kernel.models.vpn import Panel, VpnAccount
from melorin.modules.vpn import capabilities as panel_caps
from melorin.modules.vpn import sync
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError, supports
from melorin.modules.vpn.adapters.registry import build_adapter, seed_adapter

log = logging.getLogger("melorin.vpn.tools")

CUSTOMER, OWNER, ADMIN = "customer", "owner", "admin"
ROLES = (CUSTOMER, OWNER, ADMIN)
GIB = 1024**3


@dataclass(frozen=True)
class Tool:
    name: str
    label: str
    capability: str | None  # adapter capability flag; None = served from Melorin's own synced data
    roles: tuple[str, ...]
    write: bool = False


TOOLS: tuple[Tool, ...] = (
    Tool("usage", "نمودار مصرف", "usage_ops", (CUSTOMER, OWNER, ADMIN)),
    Tool("presence", "آخرین اتصال", None, (OWNER, ADMIN)),
    Tool("devices", "دستگاه‌ها", "device_ops", (CUSTOMER, OWNER, ADMIN)),
    Tool("devices_manage", "حذف / ریست دستگاه‌ها", "device_ops", (CUSTOMER, OWNER, ADMIN), write=True),
    Tool("rotate", "لینک اشتراک جدید", "subscription_rotate", (CUSTOMER, OWNER, ADMIN), write=True),
    Tool("suspend", "تعلیق / فعال‌سازی", "suspend", (OWNER, ADMIN), write=True),
    Tool("adjust", "جبران حجم و زمان", "extend", (ADMIN,), write=True),
    Tool("change_plan", "تغییر پلن اکانت", "next_plan_ops", (ADMIN,), write=True),  # PG-09: served by plans.change_plan
)
_BY_NAME = {t.name: t for t in TOOLS}

# Statuses a tool may act on. Never an archived / revoked / not-yet-provisioned account.
_LIVE = (VpnStatus.ACTIVE, VpnStatus.SUSPENDED, VpnStatus.EXPIRED, VpnStatus.LIMITED)
USAGE_PERIODS = ("hour", "day")
MAX_USAGE_DAYS = 90
ROTATE_COOLDOWN_SECONDS = 20.0
MAX_ADJUST_DAYS = 365
MAX_ADJUST_GB = 1024

_last_rotate: dict[uuid.UUID, float] = {}


# ------------------------------------------------------------------------------------------------------------- plumbing
def _is_live(account: VpnAccount) -> bool:
    return account.archived_at is None and account.status in _LIVE and bool(account.panel_id)


def _tool(name: str) -> Tool:
    return _BY_NAME[name]


def _panel_error(exc: PanelError) -> AppError:
    if exc.kind == ErrorKind.PERMANENT:
        return AppError("PANEL_REJECTED", "پنل این درخواست را نپذیرفت؛ بعداً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.", 409)
    return AppError("PANEL_UNAVAILABLE", "پنل در حال حاضر پاسخ نمی‌دهد؛ چند لحظه بعد دوباره تلاش کنید.", 503)


async def _close(adapter) -> None:
    try:
        await adapter.close()
    except Exception:
        log.warning("adapter close failed", exc_info=True)


def _reason(tool: Tool, role: str, account: VpnAccount, panel: Panel | None) -> str | None:
    """Why this tool cannot be used right now (Core's own words, shown as is). ``None`` = available."""
    if role not in tool.roles:
        return "این امکان برای شما فعال نیست."
    if not _is_live(account):
        return "این اکانت در وضعیتی نیست که بتوان این کار را انجام داد."
    if tool.capability is None:
        return None
    if panel is None or not panel_caps.capabilities_of(panel).has(tool.capability):
        return "پنل این اکانت از این امکان پشتیبانی نمی‌کند."
    return None


def available(account: VpnAccount, role: str, panel: Panel | None) -> list[dict]:
    """The tool matrix a channel shows: every tool the role has, with ``available`` and the reason when not."""
    out = []
    for tool in TOOLS:
        if role not in tool.roles:
            continue
        reason = _reason(tool, role, account, panel)
        out.append({"tool": tool.name, "label": tool.label, "write": tool.write, "available": reason is None, "reason": reason})
    return out


async def _open(session: AsyncSession, account: VpnAccount, role: str, name: str):
    """Check role / account state / panel capability, then return ``(adapter, panel)`` seeded for this account."""
    tool = _tool(name)
    panel = await session.get(Panel, account.panel_id) if account.panel_id else None
    reason = _reason(tool, role, account, panel)
    if reason:
        status = 403 if role not in tool.roles else 409
        raise AppError("TOOL_UNAVAILABLE", reason, status)
    adapter = build_adapter(panel)
    seed_adapter(adapter, account)
    if tool.capability and not supports(adapter, tool.capability):
        await _close(adapter)
        raise AppError("TOOL_UNAVAILABLE", "پنل این اکانت از این امکان پشتیبانی نمی‌کند.", 409)
    return adapter, panel


def _audit(session, account: VpnAccount, action: str, *, actor_id, role: str, data: dict | None = None) -> None:
    audit.record(
        session,
        f"vpn_account.{action}",
        actor_id=actor_id,
        actor_type={CUSTOMER: "user", OWNER: "reseller", ADMIN: "admin"}[role],
        entity_type="vpn_account",
        entity_id=account.id,
        store_id=account.store_id,
        data={"role": role, "username": account.username, **(data or {})},
    )


# ------------------------------------------------------------------------------------------------------------- read tools
def _num(row: dict, *keys: str) -> int:
    for key in keys:
        value = row.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return int(value)
    return 0


def _when(row: dict) -> str | None:
    for key in ("period_start", "date", "start", "created_at", "time"):
        if row.get(key):
            return str(row[key])
    return None


def normalise_usage(rows: list[dict]) -> dict:
    """Panel usage rows -> ``{"points": [{"at", "used_bytes", "node_id"}], "total_bytes"}`` (per period, summed over nodes)."""
    merged: dict[str | None, int] = {}
    per_node: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        used = _num(row, "total", "used_traffic", "value", "usage")
        at = _when(row)
        merged[at] = merged.get(at, 0) + used
        if row.get("node_id") is not None:
            per_node.append({"at": at, "used_bytes": used, "node_id": row.get("node_id")})
    points = [{"at": at, "used_bytes": used} for at, used in sorted(merged.items(), key=lambda kv: (kv[0] is None, kv[0] or ""))]
    return {"points": points, "by_node": per_node, "total_bytes": sum(merged.values())}


async def usage(session: AsyncSession, account: VpnAccount, *, role: str, period: str = "day", days: int = 30) -> dict:
    if period not in USAGE_PERIODS:
        raise AppError("BAD_PERIOD", "بازه‌ی نمودار نامعتبر است.", 400)
    days = max(1, min(int(days), MAX_USAGE_DAYS))
    adapter, _panel = await _open(session, account, role, "usage")
    now = utcnow()
    try:
        rows = await adapter.get_usage(account.username, start=now - dt.timedelta(days=days), end=now, period=period)
    except PanelError as exc:
        raise _panel_error(exc) from exc
    finally:
        await _close(adapter)
    out = normalise_usage(rows)
    if role == CUSTOMER:
        out["by_node"] = []  # which servers carried the traffic is operational detail, not a customer view
    return {"period": period, "days": days, **out}


def presence(account: VpnAccount, role: str, panel: Panel | None = None) -> dict:
    """Last seen / state from the synced row (no panel call, no IPs). Owner and admin only."""
    reason = _reason(_tool("presence"), role, account, panel)
    if reason:
        raise AppError("TOOL_UNAVAILABLE", reason, 403 if role not in _tool("presence").roles else 409)
    now = utcnow()
    seen = sync.aware(account.online_at)
    return {
        "online_at": account.online_at,
        "online_now": bool(seen and now - seen <= dt.timedelta(minutes=5)),
        "never_connected": seen is None,
        "remote_status": account.remote_status,
        "lifetime_used_bytes": account.lifetime_used_traffic,
        "last_synced_at": account.last_synced_at,
    }


def _device(row: dict) -> dict:
    hwid = str(row.get("hwid") or row.get("id") or "")
    return {
        "hwid": hwid,
        "label": row.get("device_model") or row.get("model") or row.get("name") or (hwid[:6] + "…" if len(hwid) > 6 else hwid),
        "platform": row.get("platform") or row.get("os"),
        "first_seen": row.get("created_at") or row.get("first_seen"),
        "last_seen": row.get("last_seen") or row.get("updated_at"),
    }


async def devices(session: AsyncSession, account: VpnAccount, *, role: str) -> dict:
    adapter, _panel = await _open(session, account, role, "devices")
    try:
        rows = await adapter.list_devices(account.username)
    except PanelError as exc:
        raise _panel_error(exc) from exc
    finally:
        await _close(adapter)
    items = [_device(r) for r in rows if isinstance(r, dict)]
    return {"items": [d for d in items if d["hwid"]], "count": len(items)}


async def delete_device(session: AsyncSession, account: VpnAccount, *, role: str, actor_id: uuid.UUID, hwid: str) -> None:
    hwid = (hwid or "").strip()
    if not hwid or len(hwid) > 200:
        raise AppError("BAD_DEVICE", "شناسه‌ی دستگاه نامعتبر است.", 400)
    adapter, _panel = await _open(session, account, role, "devices_manage")
    try:
        await adapter.delete_device(account.username, hwid)  # idempotent: an already-forgotten device is not an error
    except PanelError as exc:
        raise _panel_error(exc) from exc
    finally:
        await _close(adapter)
    _audit(session, account, "device_deleted", actor_id=actor_id, role=role, data={"hwid_prefix": hwid[:6]})
    await session.commit()


async def reset_devices(session: AsyncSession, account: VpnAccount, *, role: str, actor_id: uuid.UUID) -> None:
    adapter, _panel = await _open(session, account, role, "devices_manage")
    try:
        await adapter.reset_devices(account.username)
    except PanelError as exc:
        raise _panel_error(exc) from exc
    finally:
        await _close(adapter)
    _audit(session, account, "devices_reset", actor_id=actor_id, role=role)
    await session.commit()


# ------------------------------------------------------------------------------------------------------------- write tools
async def rotate_subscription(session: AsyncSession, account: VpnAccount, *, role: str, actor_id: uuid.UUID) -> VpnAccount:
    """New subscription link. The OLD link stops working at once on the panel, so the call is rate-limited per account."""
    now = time.monotonic()
    if now - _last_rotate.get(account.id, -ROTATE_COOLDOWN_SECONDS) < ROTATE_COOLDOWN_SECONDS:
        raise AppError("TOO_FAST", "لینک همین الان عوض شده است؛ چند لحظه صبر کنید.", 429)
    adapter, _panel = await _open(session, account, role, "rotate")
    try:
        pa = await adapter.rotate_subscription(account.username)
    except PanelError as exc:
        raise _panel_error(exc) from exc
    finally:
        await _close(adapter)
    if len(_last_rotate) > 5000:
        _last_rotate.clear()
    _last_rotate[account.id] = now
    await sync.apply_remote(session, account, pa, notify=False)
    _audit(session, account, "subscription_rotated", actor_id=actor_id, role=role)
    await session.commit()
    return account


async def suspend(session: AsyncSession, account: VpnAccount, *, role: str, actor_id: uuid.UUID, reason: str | None = None) -> VpnAccount:
    """Switch the account off on the panel (owner / admin). Idempotent: an already-suspended account stays suspended."""
    adapter, _panel = await _open(session, account, role, "suspend")
    if account.status in (VpnStatus.EXPIRED, VpnStatus.LIMITED):
        await _close(adapter)
        raise AppError("ACCOUNT_NOT_ACTIVE", "این اکانت منقضی یا تمام‌شده است و تعلیق معنا ندارد.", 409)
    try:
        await adapter.suspend_account(account.username)
    except PanelError as exc:
        raise _panel_error(exc) from exc
    finally:
        await _close(adapter)
    account.status, account.remote_status = VpnStatus.SUSPENDED, "disabled"
    _audit(session, account, "suspended", actor_id=actor_id, role=role, data={"reason": (reason or "")[:300]})
    await session.commit()
    return account


async def resume(session: AsyncSession, account: VpnAccount, *, role: str, actor_id: uuid.UUID) -> VpnAccount:
    adapter, _panel = await _open(session, account, role, "suspend")
    expires = sync.aware(account.expires_at)
    if account.status != VpnStatus.SUSPENDED or (expires is not None and expires <= utcnow()):
        await _close(adapter)
        raise AppError("ACCOUNT_NOT_SUSPENDED", "فقط اکانتِ تعلیق‌شده و منقضی‌نشده را می‌توان فعال کرد.", 409)
    try:
        await adapter.resume_account(account.username)
    except PanelError as exc:
        raise _panel_error(exc) from exc
    finally:
        await _close(adapter)
    account.status, account.remote_status = VpnStatus.ACTIVE, "active"
    _audit(session, account, "resumed", actor_id=actor_id, role=role)
    await session.commit()
    return account


async def adjust(
    session: AsyncSession,
    account: VpnAccount,
    *,
    actor_id: uuid.UUID,
    add_days: int = 0,
    add_traffic_gb: int = 0,
    reason: str,
    role: str = ADMIN,
) -> VpnAccount:
    """Compensation (admin only): add days and/or volume on top of what the PANEL shows right now.

    Built from a fresh panel read and written as absolute values (``extend_account``), then mirrored back; before/after go to the
    audit trail together with the reason. An unlimited account cannot receive that kind of addition.
    """
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise AppError("REASON_REQUIRED", "برای جبران، دلیل را بنویسید.", 400)
    if not (0 <= int(add_days) <= MAX_ADJUST_DAYS) or not (0 <= int(add_traffic_gb) <= MAX_ADJUST_GB) or not (add_days or add_traffic_gb):
        raise AppError("BAD_ADJUSTMENT", f"روز (تا {MAX_ADJUST_DAYS}) یا حجم (تا {MAX_ADJUST_GB} گیگابایت) نامعتبر است.", 400)
    adapter, _panel = await _open(session, account, role, "adjust")
    try:
        remote = await adapter.get_account(account.username)
        if remote is None:
            raise AppError("MISSING_ON_PANEL", "این اکانت روی پنل پیدا نشد.", 409)
        now = utcnow()
        old_expire, old_limit = sync.aware(remote.expire_at), int(remote.traffic_limit_bytes or 0)
        if add_days and old_expire is None:
            raise AppError("UNLIMITED_TIME", "این اکانت زمان نامحدود دارد؛ افزودن روز معنا ندارد.", 409)
        if add_traffic_gb and old_limit == 0:
            raise AppError("UNLIMITED_TRAFFIC", "این اکانت حجم نامحدود دارد؛ افزودن حجم معنا ندارد.", 409)
        new_expire = max(old_expire, now) + dt.timedelta(days=int(add_days)) if add_days else old_expire
        new_limit = old_limit + int(add_traffic_gb) * GIB if add_traffic_gb else old_limit
        pa = await adapter.extend_account(account.username, expire_at=new_expire, traffic_bytes=new_limit)
    except PanelError as exc:
        raise _panel_error(exc) from exc
    finally:
        await _close(adapter)
    await sync.apply_remote(session, account, pa, notify=False)
    _audit(
        session,
        account,
        "adjusted",
        actor_id=actor_id,
        role=role,
        data={
            "reason": reason[:300],
            "add_days": int(add_days),
            "add_traffic_gb": int(add_traffic_gb),
            "before": {"expires_at": old_expire.isoformat() if old_expire else None, "traffic_limit_bytes": old_limit},
            "after": {"expires_at": new_expire.isoformat() if new_expire else None, "traffic_limit_bytes": new_limit},
        },
    )
    await session.commit()
    return account
