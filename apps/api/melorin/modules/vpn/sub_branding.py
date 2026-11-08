"""PG-12: per-store subscription-page branding (name, support link, logo) as an explicit, audited ADMIN action.

What the store owner edits: three plain fields kept in ``stores.branding["sub"]`` (no migration): ``display_name``, ``support_url``,
``logo_url``. Saving them changes NOTHING on a panel (decision 3: Melorin does not write panel settings on its own).

What "apply" does: with the panel name typed as confirmation, it writes exactly three keys into the ``custom_variables`` of THAT store's
panel admin (``melorin_brand_name`` / ``melorin_support_url`` / ``melorin_logo_url``) and leaves every other key the panel holds alone.
It reads the admin back afterwards and only reports success when the panel really kept the values; otherwise it restores what it saw
before. ``revert`` removes the three keys. Both record an audit event with key names and a digest, never the values.

What Melorin never does: it does not write ``sub_template`` or any HTML. A store-chosen template would run on the subscription domain
(XSS), so the template stays what the panel operator installed; it only has to read the three variables above. Values are checked here
(plain text, no markup, https/tg links only) because the panel's page may print them.

Not verified live: PasarGuard 5.6.0 accepts ``custom_variables`` on ``AdminModify`` (contract fixture) but its docs do not say how a page
reads them, so the read-back check above is the only proof; the first real apply should be done on a test store.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from urllib.parse import urlsplit

from sqlalchemy import select

from melorin.core import audit
from melorin.core.db import utcnow
from melorin.core.errors import AppError
from melorin.kernel.models.stores import Store
from melorin.kernel.models.vpn import Panel, PanelAdmin
from melorin.modules.vpn.adapters import registry
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError

log = logging.getLogger("melorin.vpn.sub_branding")

FIELDS = ("display_name", "support_url", "logo_url")
VARIABLES = {"display_name": "melorin_brand_name", "support_url": "melorin_support_url", "logo_url": "melorin_logo_url"}
LIMITS = {"display_name": 64, "support_url": 512, "logo_url": 512}
_UNSAFE = re.compile(r"[<>\"'`\\\x00-\x1f\x7f]")
_IMG = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif")


class BrandingError(AppError):
    def __init__(self, message: str):
        super().__init__("BRANDING_INVALID", message, 422)


def clean(raw: dict) -> dict:
    """Validated fields. Unknown keys are refused, ``None`` = unchanged, ``""`` = clear. Only plain text and https (tg for support) links."""
    if not isinstance(raw, dict):
        raise BrandingError("branding must be an object")
    out: dict[str, str] = {}
    for key, value in raw.items():
        if key not in FIELDS:
            raise BrandingError(f"field not allowed: {key}")
        if value is None:
            continue
        text = str(value).strip()
        if len(text) > LIMITS[key]:
            raise BrandingError(f"{key} is too long (max {LIMITS[key]})")
        if text and _UNSAFE.search(text):
            raise BrandingError(f"{key} contains characters that are not allowed")
        if text and key != "display_name":
            parts = urlsplit(text)
            ok = parts.scheme == "https" and bool(parts.hostname) and not parts.username and not parts.password
            if key == "support_url":
                ok = ok or (parts.scheme == "tg" and bool(parts.netloc or parts.path))
            if key == "logo_url" and ok and not parts.path.lower().endswith(_IMG):
                ok = False
            if not ok:
                raise BrandingError(f"{key} must be an https link" + (" to an image" if key == "logo_url" else ""))
        out[key] = text
    return out


def get(store: Store) -> dict:
    sub = (store.branding or {}).get("sub")
    return {k: str(sub[k]) for k in FIELDS if isinstance(sub, dict) and sub.get(k)}


def save(store: Store, changes: dict) -> dict:
    """Store the owner's fields (no panel call). Other keys of ``store.branding`` are kept."""
    fields = {**get(store), **clean(changes)}
    fields = {k: v for k, v in fields.items() if v}
    base = dict(store.branding or {})
    if fields:
        base["sub"] = fields
    else:
        base.pop("sub", None)
    store.branding = base
    return fields


def wanted_variables(store: Store) -> dict[str, str]:
    return {VARIABLES[k]: v for k, v in get(store).items()}


def digest(variables: dict[str, str]) -> str:
    return hashlib.sha256("\n".join(f"{k}={variables[k]}" for k in sorted(variables)).encode()).hexdigest()[:16]


def _applied(store: Store, panel_id: uuid.UUID) -> dict | None:
    rec = ((store.branding or {}).get("sub_applied") or {}).get(str(panel_id))
    return rec if isinstance(rec, dict) else None


def _set_applied(store: Store, panel_id: uuid.UUID, rec: dict | None) -> None:
    base = dict(store.branding or {})
    applied = dict(base.get("sub_applied") or {})
    if rec is None:
        applied.pop(str(panel_id), None)
    else:
        applied[str(panel_id)] = rec
    if applied:
        base["sub_applied"] = applied
    else:
        base.pop("sub_applied", None)
    store.branding = base


async def _row(session, store: Store, panel: Panel) -> PanelAdmin:
    if panel.kind != "pasarguard":
        raise AppError("NOT_PASARGUARD", "Subscription branding is only available for PasarGuard panels.", 422)
    row = await session.scalar(select(PanelAdmin).where(PanelAdmin.store_id == store.id, PanelAdmin.panel_id == panel.id))
    if row is None or row.status != "active" or not row.remote_id:
        raise AppError("STORE_ADMIN_NOT_READY", "This store has no active admin on that panel yet.", 409)
    return row


def _adapter(panel: Panel):
    adapter = registry.build_adapter(panel)
    if not hasattr(adapter, "read_custom_variables"):
        raise AppError("NOT_SUPPORTED", "This panel type cannot carry subscription branding.", 422)
    return adapter


async def _close(adapter) -> None:
    close = getattr(adapter, "close", None)
    if callable(close):
        try:
            res = close()
            if hasattr(res, "__await__"):
                await res
        except Exception:
            log.debug("sub branding: adapter close failed", exc_info=True)


async def preview(session, store: Store, panel: Panel) -> dict:
    """Read-only: what the panel holds now for our three keys versus what the store wants."""
    row = await _row(session, store, panel)
    want = wanted_variables(store)
    adapter = _adapter(panel)
    try:
        try:
            current = await adapter.read_custom_variables(row.username)
        except PanelError as exc:
            return {"live": False, "note": "پنل موقتاً در دسترس نیست.", "wanted": want, "detail": (exc.message or "")[:200]}
    finally:
        await _close(adapter)
    if current is None:
        return {"live": False, "note": "ادمین فروشگاه روی پنل پیدا نشد.", "wanted": want}
    ours = {k: current[k] for k in VARIABLES.values() if k in current}
    rec = _applied(store, panel.id)
    return {
        "live": True,
        "wanted": want,
        "on_panel": ours,
        "in_sync": ours == want,
        "last_applied": rec,
        "other_keys_kept": sorted(k for k in current if k not in VARIABLES.values()),
    }


async def _write_verified(adapter, row: PanelAdmin, before: dict, after: dict) -> None:
    """Write ``after``; read back; on any mismatch or error put ``before`` back and raise."""
    try:
        await adapter.write_custom_variables(row.remote_id, after)
        seen = await adapter.read_custom_variables(row.username)
        if seen != after:
            raise PanelError(ErrorKind.PERMANENT, "panel did not keep the values")
    except PanelError as exc:
        try:
            await adapter.write_custom_variables(row.remote_id, before)
        except Exception:
            log.warning("sub branding: restore failed for admin %s", row.username, exc_info=True)
        detail = (getattr(exc, "message", None) or str(exc))[:200]
        raise AppError("BRANDING_APPLY_FAILED", f"Panel did not accept the branding: {detail}", 502) from exc


async def apply(session, store: Store, panel: Panel, *, actor_id=None) -> dict:
    """Write the store's three variables into its panel admin's ``custom_variables`` (other keys kept), verified by reading back."""
    want = wanted_variables(store)
    if not want:
        raise AppError("BRANDING_EMPTY", "Nothing to apply: the store has no branding fields set.", 422)
    row = await _row(session, store, panel)
    adapter = _adapter(panel)
    try:
        try:
            before = await adapter.read_custom_variables(row.username)
        except PanelError as exc:
            raise AppError("PANEL_UNAVAILABLE", "پنل موقتاً در دسترس نیست.", 503) from exc
        if before is None:
            raise AppError("STORE_ADMIN_NOT_READY", "The store admin does not exist on the panel.", 409)
        after = {k: v for k, v in before.items() if k not in VARIABLES.values()} | want
        if after != before:
            await _write_verified(adapter, row, before, after)
    finally:
        await _close(adapter)
    stamp = {"digest": digest(want), "at": utcnow().isoformat(), "keys": sorted(want)}
    _set_applied(store, panel.id, stamp)
    audit.record(
        session,
        "panel.sub_branding.applied",
        actor_id=actor_id,
        actor_type="admin",
        entity_type="store",
        entity_id=store.id,
        store_id=store.id,
        data={"panel_id": str(panel.id), "keys": stamp["keys"], "digest": stamp["digest"], "changed": after != before},
    )
    await session.commit()
    return {"applied": True, "changed": after != before, "keys": stamp["keys"], "digest": stamp["digest"]}


async def revert(session, store: Store, panel: Panel, *, actor_id=None) -> dict:
    """Remove our three keys from the store admin on the panel (every other key stays)."""
    row = await _row(session, store, panel)
    adapter = _adapter(panel)
    try:
        try:
            before = await adapter.read_custom_variables(row.username)
        except PanelError as exc:
            raise AppError("PANEL_UNAVAILABLE", "پنل موقتاً در دسترس نیست.", 503) from exc
        if before is None:
            raise AppError("STORE_ADMIN_NOT_READY", "The store admin does not exist on the panel.", 409)
        after = {k: v for k, v in before.items() if k not in VARIABLES.values()}
        if after != before:
            await _write_verified(adapter, row, before, after)
    finally:
        await _close(adapter)
    _set_applied(store, panel.id, None)
    audit.record(
        session,
        "panel.sub_branding.reverted",
        actor_id=actor_id,
        actor_type="admin",
        entity_type="store",
        entity_id=store.id,
        store_id=store.id,
        data={"panel_id": str(panel.id), "removed": sorted(set(before) - set(after))},
    )
    await session.commit()
    return {"applied": False, "removed": sorted(set(before) - set(after))}
