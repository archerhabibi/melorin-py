"""One PasarGuard admin (role Operator) per store and panel.

* The Main Store and every reseller store get their OWN admin on every enabled PasarGuard panel (``panel_admins`` row per
  (panel, store)). Every account sold through a store - the reseller's own and their customers' - is created under that admin.
* Rows are planned by :func:`plan` (DB only) and made real on the panel by :func:`sync_all` (the worker's
  ``panel_admin_sync_job`` every minute, "sync now" in the admin API, and lazily by :func:`owner_for` while provisioning).
  Everything is idempotent: a new reseller, a new panel, or a reseller that existed long before the panel was added all end in
  the same state.
* "Profile & contact" is optional and edited by the Melorin admin only. A reseller files a change request
  (``PanelAdminChangeRequest``); the admin applies it (optionally edited) or rejects it.
* A panel opts out with ``config.admin_per_store = false`` (e.g. when its Melorin credential is not an owner).
"""

from __future__ import annotations

import logging
import re
import secrets
import string
import uuid
from urllib.parse import urlsplit

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from melorin.core.crypto import decrypt, encrypt
from melorin.core.db import utcnow
from melorin.kernel.models.stores import Store
from melorin.kernel.models.vpn import Panel, PanelAdmin, VpnAccount
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError

log = logging.getLogger("melorin.panel_admins")

ROLE = "operator"
# "Profile & contact" fields (all optional). ``sub_domain`` changes subscription links, ``note`` is internal: admin only.
PROFILE_FIELDS = ("profile_title", "support_url", "telegram_id", "discord_webhook", "sub_domain", "note")
REQUESTABLE_FIELDS = ("profile_title", "support_url", "telegram_id", "discord_webhook")
FIELD_LABELS = {
    "profile_title": "عنوان پروفایل",
    "support_url": "لینک پشتیبانی",
    "telegram_id": "آیدی تلگرام",
    "discord_webhook": "وبهوک دیسکورد",
    "sub_domain": "دامنهٔ اشتراک",
    "note": "یادداشت داخلی",
}
_UNSAFE = re.compile(r"[<>\"'`\x00-\x1f]")


def describe_fields(fields) -> str:
    """Persian field names for an alert (values are never copied into notifications: a webhook URL is a secret)."""
    return "، ".join(FIELD_LABELS.get(f, f) for f in sorted(fields)) or "—"


class ProfileError(ValueError):
    """A profile value PasarGuard would refuse (or that is unsafe to show on subscription pages)."""


def managed(panel: Panel) -> bool:
    return panel.kind == "pasarguard" and (panel.config or {}).get("admin_per_store") is not False


def admin_username(store: Store) -> str:
    """Stable, panel-valid (<= 34 chars, ``[a-z0-9_]``) username: ``ml_main`` / ``rs_<slug>``."""
    if store.kind == "main":
        return "ml_main"
    slug = re.sub(r"[^a-z0-9]+", "_", (store.slug or str(store.id)).lower()).strip("_")
    slug = re.sub(r"^reseller_?", "", slug) or store.id.hex[:8]
    return f"rs_{slug}"[:34]


def pick_username(store: Store, taken: set[str]) -> str:
    """First free panel login for ``store``: the plain ``admin_username`` unless ANOTHER store already holds it on that panel, then the
    same name with a growing slice of the store id (still <= 34 chars). Two stores must never share one panel admin."""
    base = admin_username(store)
    if base not in taken:
        return base
    for width in (6, 10, 16, 32):
        candidate = f"{base[: 34 - width - 1]}_{store.id.hex[:width]}"
        if candidate not in taken:
            return candidate
    raise PanelError(ErrorKind.PERMANENT, f"no free panel admin name for store {store.id}")


def generate_password() -> str:
    """Meets PasarGuard's rule (>= 12 chars, 2+ digits, 2+ upper, 2+ lower, 1+ special; <= 72 bytes)."""
    rng = secrets.SystemRandom()
    chars = (
        [secrets.choice(string.ascii_uppercase) for _ in range(4)]
        + [secrets.choice(string.ascii_lowercase) for _ in range(6)]
        + [secrets.choice(string.digits) for _ in range(4)]
        + [secrets.choice("!@#$%^&*-_=+") for _ in range(2)]
    )
    rng.shuffle(chars)
    return "".join(chars)


# ----------------------------------------------------------------------------- profile validation
def clean_profile(raw: dict, *, allowed: tuple[str, ...] = PROFILE_FIELDS) -> dict:
    """Validated subset of ``raw``. Unknown or not-allowed keys are rejected, ``None`` means "unchanged", "" clears a text field."""
    if not isinstance(raw, dict):
        raise ProfileError("profile must be an object")
    out: dict = {}
    for key, value in raw.items():
        if key not in PROFILE_FIELDS or key not in allowed:
            raise ProfileError(f"field not allowed: {key}")
        if value is None:
            continue
        if key == "telegram_id":
            try:
                n = int(value)
            except (TypeError, ValueError) as exc:
                raise ProfileError("telegram_id must be a number") from exc
            if n <= 0:
                raise ProfileError("telegram_id must be positive")
            out[key] = n
            continue
        text = str(value).strip()
        limit = {"profile_title": 128, "support_url": 512, "discord_webhook": 512, "sub_domain": 256, "note": 500}[key]
        if len(text) > limit:
            raise ProfileError(f"{key} is too long (max {limit})")
        if text and _UNSAFE.search(text):
            raise ProfileError(f"{key} contains unsafe characters")
        if text and key in ("support_url", "sub_domain", "discord_webhook"):
            parts = urlsplit(text)
            ok = parts.scheme in ("https", "http") and bool(parts.hostname) and not parts.username
            if key == "support_url":
                ok = ok or (parts.scheme in ("tg",) and bool(parts.netloc or parts.path))
            if key == "discord_webhook":
                ok = ok and parts.scheme == "https" and parts.hostname in ("discord.com", "discordapp.com")
            if not ok:
                raise ProfileError(f"{key} is not a valid URL")
        out[key] = text
    return out


def public_row(row: PanelAdmin, *, panel: Panel | None = None, store: Store | None = None) -> dict:
    """Never includes the password."""
    return {
        "id": row.id,
        "panel_id": row.panel_id,
        "panel_name": panel.name if panel else None,
        "store_id": row.store_id,
        "store_name": store.name if store else None,
        "store_kind": store.kind if store else None,
        "username": row.username,
        "role": (panel.config or {}).get("admin_role") or ROLE if panel else ROLE,
        "status": row.status,
        "last_error": row.last_error,
        "synced_at": row.synced_at,
        "adopted": row.adopted_at is not None,
        "profile": row.profile or {},
        "profile_synced": bool(row.profile_synced),
    }


# ----------------------------------------------------------------------------- planning (DB only)
def _new_row(panel: Panel, store: Store, username: str | None = None) -> PanelAdmin:
    return PanelAdmin(
        panel_id=panel.id,
        store_id=store.id,
        username=username or admin_username(store),
        password_enc=encrypt(generate_password()),
        status="pending",
        profile_synced=True,
    )


async def _create_row(session, panel: Panel, store: Store) -> tuple[PanelAdmin, bool]:
    """The (panel, store) row, created when missing. Returns ``(row, created)``.

    Safe against the worker and provisioning racing for the same row, and against a login clash with another store: each insert
    runs in its own SAVEPOINT; losing the race means "re-read what the winner made", a clash means "pick the next free name"."""
    for _ in range(4):
        row = await session.scalar(select(PanelAdmin).where(PanelAdmin.panel_id == panel.id, PanelAdmin.store_id == store.id))
        if row is not None:
            return row, False
        taken = set((await session.scalars(select(PanelAdmin.username).where(PanelAdmin.panel_id == panel.id))).all())
        row = _new_row(panel, store, pick_username(store, taken))
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
            return row, True
        except IntegrityError:
            continue  # somebody else got there first (same store, or the same login): look again
    raise PanelError(ErrorKind.TRANSIENT, f"could not allocate a panel admin for store {store.id}")


async def plan(session, *, panel: Panel | None = None) -> int:
    """Create the missing (panel, store) rows for every managed panel x every active store. Returns how many were added."""
    panels = (
        [panel] if panel else (await session.scalars(select(Panel).where(Panel.is_enabled.is_(True), Panel.kind == "pasarguard"))).all()
    )
    panels = [p for p in panels if managed(p)]
    if not panels:
        return 0
    stores = (await session.scalars(select(Store).where(Store.status == "active", Store.kind.in_(["main", "reseller"])))).all()
    have = {
        (r.panel_id, r.store_id)
        for r in (await session.scalars(select(PanelAdmin).where(PanelAdmin.panel_id.in_([p.id for p in panels])))).all()
    }
    added = 0
    for p in panels:
        for st in stores:
            if (p.id, st.id) not in have:
                _, created = await _create_row(session, p, st)
                added += int(created)
    return added


# ----------------------------------------------------------------------------- panel work
async def _push(session, row: PanelAdmin, panel: Panel, store: Store, adapter) -> None:
    """Make the row real on the panel: admin exists (Operator), profile applied, existing accounts adopted. Never raises."""
    try:
        password = decrypt(row.password_enc) or generate_password()
        if not row.password_enc:
            row.password_enc = encrypt(password)
        remote = await adapter.ensure_admin(
            row.username, password, role=(panel.config or {}).get("admin_role") or ROLE, profile=row.profile
        )
        row.remote_id = int(remote["id"]) if remote.get("id") is not None else row.remote_id
        row.profile_synced = True
        row.status, row.last_error, row.synced_at = "active", None, utcnow()
        if row.adopted_at is None:
            refs = [
                r
                for r in (
                    await session.scalars(
                        select(VpnAccount.panel_ref).where(
                            VpnAccount.panel_id == panel.id,
                            VpnAccount.store_id == store.id,
                            VpnAccount.panel_ref.is_not(None),
                            VpnAccount.archived_at.is_(None),
                        )
                    )
                ).all()
            ]
            if refs:
                await adapter.bulk_set_owner(refs, row.username)
            row.adopted_at = utcnow()
    except PanelError as exc:
        row.status, row.last_error = "error", exc.message[:500]
    except Exception as exc:  # a broken row must never stop the others
        log.warning("panel admin sync failed row=%s", row.id, exc_info=True)
        row.status, row.last_error = "error", str(exc)[:500]


async def sync_all(session, *, limit: int = 25, panel: Panel | None = None) -> dict:
    """Plan, then bring up to ``limit`` unfinished rows in line with the panels. Safe to run concurrently with provisioning."""
    from melorin.modules.vpn.adapters import registry

    added = await plan(session, panel=panel)
    stmt = select(PanelAdmin).where(
        or_(PanelAdmin.status != "active", PanelAdmin.profile_synced.is_(False), PanelAdmin.adopted_at.is_(None))
    )
    if panel:
        stmt = stmt.where(PanelAdmin.panel_id == panel.id)
    rows = (await session.scalars(stmt.order_by(PanelAdmin.created_at).limit(limit))).all()
    done = failed = 0
    adapters: dict[uuid.UUID, object] = {}
    try:
        for row in rows:
            p = panel if panel and panel.id == row.panel_id else await session.get(Panel, row.panel_id)
            st = await session.get(Store, row.store_id)
            if not p or not st or not p.is_enabled or not managed(p):
                continue
            if p.id not in adapters:
                try:
                    adapters[p.id] = registry.build_adapter(p)
                except Exception as exc:
                    row.status, row.last_error = "error", (getattr(exc, "message", None) or str(exc))[:500]
                    failed += 1
                    continue
            await _push(session, row, p, st, adapters[p.id])
            done, failed = done + (row.status == "active"), failed + (row.status != "active")
    finally:
        for a in adapters.values():
            try:
                await a.close()
            except Exception:
                log.warning("adapter close failed", exc_info=True)
    await session.commit()
    return {"planned": added, "synced": done, "failed": failed}


async def owner_for(session, panel: Panel, store_id: uuid.UUID | None, adapter) -> str | None:
    """Username of the admin that must own a NEW account of ``store_id`` on ``panel`` (None = panel not managed).

    Creates/repairs the admin on the spot when the worker has not yet. If it cannot be made ready a TRANSIENT PanelError is
    raised: the order is retried instead of creating the account under the wrong admin."""
    if store_id is None or not managed(panel) or not hasattr(adapter, "ensure_admin"):
        return None
    store = await session.get(Store, store_id)
    if store is None:
        return None
    row, _ = await _create_row(session, panel, store)
    if row.status != "active":
        await _push(session, row, panel, store, adapter)
        await session.commit()
    if row.status != "active":
        raise PanelError(ErrorKind.TRANSIENT, f"panel admin {row.username} is not ready: {row.last_error}")
    return row.username


# ----------------------------------------------------------------------------- admin operations
async def apply_profile(session, store_id: uuid.UUID, changes: dict, *, panel_id: uuid.UUID | None = None) -> list[dict]:
    """Admin edit of "Profile & contact" for a store on one panel (or all). Saved locally first, then pushed; a panel that
    refuses is reported and retried by the worker (``profile_synced`` stays False)."""
    from melorin.modules.vpn.adapters import registry

    clean = clean_profile(changes)
    stmt = select(PanelAdmin).where(PanelAdmin.store_id == store_id)
    if panel_id:
        stmt = stmt.where(PanelAdmin.panel_id == panel_id)
    rows = (await session.scalars(stmt)).all()
    results = []
    for row in rows:
        row.profile = {**(row.profile or {}), **clean}
        row.profile_synced = False
        panel = await session.get(Panel, row.panel_id)
        error = None
        if row.status == "active" and row.remote_id and panel and panel.is_enabled:
            adapter = None
            try:
                adapter = registry.build_adapter(panel)
                await adapter.update_admin_profile(row.remote_id, clean)
                row.profile_synced = True
            except PanelError as exc:
                error = exc.message[:300]
            except Exception as exc:
                error = str(exc)[:300]
            finally:
                if adapter is not None:
                    await adapter.close()
        results.append({"panel_id": row.panel_id, "username": row.username, "synced": row.profile_synced, "error": error})
    return results


async def reset_password(session, row: PanelAdmin, panel: Panel) -> str:
    """Rotate the store admin's panel password so that the database and the panel can never disagree for good.

    1. the NEW secret is saved first and the row is flagged ``profile_synced = False``: from this moment the worker's sync would push
       exactly this password, so a crash (or a failed commit) after the panel changed still converges;
    2. the panel is updated;
    3. a clean panel refusal restores the previous secret (the admin was told it failed, and the old password still works)."""
    from melorin.modules.vpn.adapters import registry

    if not row.remote_id:
        raise PanelError(ErrorKind.PERMANENT, "admin is not created on the panel yet")
    password = generate_password()
    previous, previous_flag = row.password_enc, row.profile_synced
    row.password_enc, row.profile_synced = encrypt(password), False
    await session.commit()
    adapter = None
    try:
        adapter = registry.build_adapter(panel)
        await adapter.update_admin_profile(row.remote_id, {}, password=password)
    except Exception:
        row.password_enc, row.profile_synced = previous, previous_flag
        await session.commit()
        raise
    finally:
        if adapter is not None:
            await adapter.close()
    row.profile_synced = True  # the caller commits this together with its audit record
    return password
