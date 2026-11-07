"""Panel user templates managed from Melorin (PG-09): one template per package (product) on a panel.

A template is how a PasarGuard panel knows a package: groups, volume, duration, device limit. Melorin keeps the mapping
``(panel, product) -> remote template id`` in ``product_templates`` and uses it for two things: queueing a prepaid renewal
(:mod:`melorin.modules.vpn.plans`) and moving an account to another package.

Rules (all admin-only, all audited):

* **Melorin only edits what it created.** A template Melorin created is ``managed``: ``sync_product`` rewrites it to the
  package's current numbers (absolute values, so a repeat changes nothing). A template an admin linked by hand
  (``link_existing``) is ``managed=False`` and is never modified; ``overview`` only reports its drift.
* **Validation before the panel is touched**: name, groups, volume, duration and device limit are checked here, so a bad
  package never produces a half-configured template.
* **Idempotent**: creating a template for a package that already has one returns the existing mapping instead of making a
  second template on the panel.
* **Capability-driven**: a panel (or credential) without ``template_ops`` is refused with a clear reason, never attempted.
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import audit
from melorin.core.errors import AppError
from melorin.kernel.models.catalog import Product
from melorin.kernel.models.vpn import Panel, ProductTemplate
from melorin.modules.vpn import capabilities as panel_caps
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError, supports
from melorin.modules.vpn.adapters.registry import build_adapter

log = logging.getLogger("melorin.vpn.templates")

GIB = 1024**3
DAY = 86400
NAME_MAX = 64
MAX_GROUPS = 50
MAX_DAYS = 3650
MAX_GB = 100_000
MAX_DEVICES = 100


# ------------------------------------------------------------------------------------------------------------- spec
def template_name(product: Product) -> str:
    """Stable, readable name on the panel: ``melorin-<code>``. The product code is unique, so the name is too."""
    return ("melorin-" + re.sub(r"[^A-Za-z0-9_.-]", "-", product.code or str(product.id)[:8]))[:NAME_MAX]


def groups_for(panel: Panel, explicit: list[int] | None = None) -> list[int]:
    """Groups a template serves: the caller's choice, else the panel's own ``config.group_ids``."""
    raw = explicit if explicit is not None else (panel.config or {}).get("group_ids") or []
    out: list[int] = []
    for g in raw:
        if isinstance(g, bool) or not isinstance(g, int | str) or not str(g).lstrip("-").isdigit():
            raise AppError("BAD_TEMPLATE", "شناسهٔ گروه نامعتبر است.", 400)
        if int(g) > 0 and int(g) not in out:
            out.append(int(g))
    return out


def spec_for(product: Product, group_ids: list[int]) -> dict:
    """The panel template that equals ``product`` (what a new account of that package would be)."""
    spec = {
        "name": template_name(product),
        "group_ids": list(group_ids),
        "data_limit": int(product.traffic_gb or 0) * GIB,  # 0 = unlimited
        "expire_duration": int(product.duration_days) * DAY,
        "status": "active",
    }
    if product.max_devices:
        spec["hwid_limit"] = int(product.max_devices)
    return spec


def validate_spec(spec: dict) -> None:
    """Refuse a package the panel could not hold sensibly. Raises ``AppError`` (400) with a Persian message."""
    name = (spec.get("name") or "").strip()
    if not name or len(name) > NAME_MAX:
        raise AppError("BAD_TEMPLATE", f"نام تمپلیت باید بین ۱ تا {NAME_MAX} نویسه باشد.", 400)
    groups = spec.get("group_ids") or []
    if not groups or len(groups) > MAX_GROUPS:
        raise AppError("BAD_TEMPLATE", "تمپلیت باید دست‌کم یک گروه داشته باشد (حداکثر ۵۰).", 400)
    days = int(spec.get("expire_duration") or 0) // DAY
    if not 1 <= days <= MAX_DAYS:
        raise AppError("BAD_TEMPLATE", f"مدت پکیج باید بین ۱ تا {MAX_DAYS} روز باشد.", 400)
    if not 0 <= int(spec.get("data_limit") or 0) <= MAX_GB * GIB:
        raise AppError("BAD_TEMPLATE", "حجم پکیج نامعتبر است.", 400)
    if not 0 <= int(spec.get("hwid_limit") or 0) <= MAX_DEVICES:
        raise AppError("BAD_TEMPLATE", "سقف دستگاه نامعتبر است.", 400)


def drift(spec: dict, remote: dict) -> dict:
    """Fields where the panel's template differs from what the package says (empty = identical)."""
    out: dict = {}
    for key in ("data_limit", "expire_duration"):
        if int(remote.get(key) or 0) != int(spec.get(key) or 0):
            out[key] = {"package": int(spec.get(key) or 0), "panel": int(remote.get(key) or 0)}
    if sorted(int(g) for g in remote.get("group_ids") or []) != sorted(spec.get("group_ids") or []):
        out["group_ids"] = {"package": sorted(spec.get("group_ids") or []), "panel": sorted(int(g) for g in remote.get("group_ids") or [])}
    return out


# ------------------------------------------------------------------------------------------------------------- plumbing
def _panel_error(exc: PanelError) -> AppError:
    if exc.kind == ErrorKind.PERMANENT:
        return AppError("PANEL_REJECTED", "پنل این درخواست را نپذیرفت؛ تنظیمات و دسترسی را بررسی کنید.", 409)
    return AppError("PANEL_UNAVAILABLE", "پنل در حال حاضر پاسخ نمی‌دهد؛ چند لحظه بعد دوباره تلاش کنید.", 503)


async def _close(adapter) -> None:
    try:
        await adapter.close()
    except Exception:
        log.warning("adapter close failed", exc_info=True)


def ensure_supported(panel: Panel) -> None:
    if panel.kind != "pasarguard" or not panel_caps.capabilities_of(panel).has("template_ops"):
        raise AppError("TEMPLATES_UNSUPPORTED", "این پنل یا دسترسی فعلی آن از مدیریت تمپلیت پشتیبانی نمی‌کند.", 409)


async def _open(panel: Panel):
    ensure_supported(panel)
    adapter = build_adapter(panel)
    if not supports(adapter, "template_ops"):
        await _close(adapter)
        raise AppError("TEMPLATES_UNSUPPORTED", "این پنل یا دسترسی فعلی آن از مدیریت تمپلیت پشتیبانی نمی‌کند.", 409)
    return adapter


def _audit(session, action: str, *, admin_id, panel: Panel, product: Product | None, data: dict) -> None:
    audit.record(
        session,
        f"panel_template.{action}",
        actor_id=admin_id,
        actor_type="admin",
        entity_type="panel",
        entity_id=panel.id,
        data={"product_id": str(product.id) if product else None, **data},
    )


def _remote_id(out: dict) -> int:
    value = out.get("id")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AppError("PANEL_REJECTED", "پنل شناسهٔ تمپلیت را برنگرداند.", 409)
    return value


# ------------------------------------------------------------------------------------------------------------- reads
async def template_id_for(session: AsyncSession, panel_id: uuid.UUID, product_id: uuid.UUID) -> int | None:
    """The panel template that carries ``product_id`` on ``panel_id`` (None = not mapped yet)."""
    return await session.scalar(
        select(ProductTemplate.remote_template_id).where(ProductTemplate.panel_id == panel_id, ProductTemplate.product_id == product_id)
    )


async def mapping_for(session: AsyncSession, panel_id: uuid.UUID, product_id: uuid.UUID) -> ProductTemplate | None:
    return await session.scalar(select(ProductTemplate).where(ProductTemplate.panel_id == panel_id, ProductTemplate.product_id == product_id))


async def overview(session: AsyncSession, panel: Panel) -> dict:
    """Templates on the panel next to the packages mapped to them, with drift. A panel that cannot be asked still lists the mappings."""
    rows = (await session.scalars(select(ProductTemplate).where(ProductTemplate.panel_id == panel.id))).all()
    products = {p.id: p for p in (await session.scalars(select(Product).where(Product.id.in_([r.product_id for r in rows])))).all()} if rows else {}
    remote: dict[int, dict] | None = None
    error: str | None = None
    try:
        adapter = await _open(panel)
    except AppError as exc:
        adapter, error = None, exc.message
    if adapter is not None:
        try:
            remote = {int(t["id"]): t for t in await adapter.list_templates() if isinstance(t, dict) and t.get("id") is not None}
        except PanelError as exc:
            error = _panel_error(exc).message
        finally:
            await _close(adapter)
    items = []
    for row in rows:
        product = products.get(row.product_id)
        entry = {
            "product_id": row.product_id,
            "product_name": product.name if product else None,
            "remote_template_id": row.remote_template_id,
            "name": row.name,
            "managed": row.managed,
            "exists_on_panel": None if remote is None else row.remote_template_id in remote,
            "drift": None,
        }
        if remote is not None and product and row.remote_template_id in remote:
            entry["drift"] = drift(spec_for(product, remote[row.remote_template_id].get("group_ids") or groups_for(panel)), remote[row.remote_template_id])
        items.append(entry)
    mapped = {r.remote_template_id for r in rows}
    unmapped = [{"id": tid, "name": t.get("name")} for tid, t in (remote or {}).items() if tid not in mapped]
    return {"supported": error is None or remote is not None, "error": error, "mappings": items, "unmapped": unmapped}


# ------------------------------------------------------------------------------------------------------------- writes
async def create_for_product(
    session: AsyncSession, panel: Panel, product: Product, *, admin_id: uuid.UUID, group_ids: list[int] | None = None
) -> ProductTemplate:
    """Create the package's template on the panel and map it. Returns the existing mapping if there already is one."""
    ensure_supported(panel)  # the root reason first: an unsupported panel is reported as such, not as a bad group list
    existing = await mapping_for(session, panel.id, product.id)
    if existing:
        return existing
    spec = spec_for(product, groups_for(panel, group_ids))
    validate_spec(spec)
    adapter = await _open(panel)
    try:
        remote_id = _remote_id(await adapter.create_template(spec))
    except PanelError as exc:
        raise _panel_error(exc) from exc
    finally:
        await _close(adapter)
    row = ProductTemplate(panel_id=panel.id, product_id=product.id, remote_template_id=remote_id, name=spec["name"], managed=True)
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:  # a parallel request mapped the package first: use its row
        existing = await mapping_for(session, panel.id, product.id)
        if existing:
            return existing
        raise
    _audit(session, "created", admin_id=admin_id, panel=panel, product=product, data={"remote_template_id": remote_id, "spec": spec})
    await session.commit()
    return row


async def link_existing(
    session: AsyncSession, panel: Panel, product: Product, remote_template_id: int, *, admin_id: uuid.UUID
) -> ProductTemplate:
    """Map the package to a template that already exists on the panel. Melorin will never modify it (``managed=False``)."""
    if isinstance(remote_template_id, bool) or int(remote_template_id) <= 0:
        raise AppError("BAD_TEMPLATE", "شناسهٔ تمپلیت نامعتبر است.", 400)
    adapter = await _open(panel)
    try:
        found = next((t for t in await adapter.list_templates() if isinstance(t, dict) and t.get("id") == int(remote_template_id)), None)
    except PanelError as exc:
        raise _panel_error(exc) from exc
    finally:
        await _close(adapter)
    if found is None:
        raise AppError("TEMPLATE_NOT_FOUND", "این تمپلیت روی پنل وجود ندارد.", 404)
    row = await mapping_for(session, panel.id, product.id)
    if row is None:
        row = ProductTemplate(panel_id=panel.id, product_id=product.id, remote_template_id=int(remote_template_id))
        session.add(row)
    row.remote_template_id, row.name, row.managed = int(remote_template_id), str(found.get("name") or "")[:120] or None, False
    _audit(session, "linked", admin_id=admin_id, panel=panel, product=product, data={"remote_template_id": int(remote_template_id)})
    await session.commit()
    return row


async def sync_product(session: AsyncSession, panel: Panel, product: Product, *, admin_id: uuid.UUID) -> dict:
    """Rewrite a MANAGED template to the package's current numbers. Idempotent; a linked (unmanaged) template is refused."""
    row = await mapping_for(session, panel.id, product.id)
    if row is None:
        raise AppError("TEMPLATE_NOT_MAPPED", "برای این پکیج هنوز تمپلیتی ثبت نشده است.", 404)
    if not row.managed:
        raise AppError("TEMPLATE_NOT_MANAGED", "این تمپلیت دستی متصل شده و ملورین آن را تغییر نمی‌دهد.", 409)
    adapter = await _open(panel)
    try:
        current = next((t for t in await adapter.list_templates() if isinstance(t, dict) and t.get("id") == row.remote_template_id), None)
        if current is None:
            raise AppError("TEMPLATE_NOT_FOUND", "تمپلیت روی پنل پیدا نشد؛ آن را دوباره بسازید.", 404)
        spec = spec_for(product, groups_for(panel, [int(g) for g in current.get("group_ids") or []] or None))
        validate_spec(spec)
        before = drift(spec, current)
        if before:
            await adapter.update_template(row.remote_template_id, spec)
    except PanelError as exc:
        raise _panel_error(exc) from exc
    finally:
        await _close(adapter)
    row.name = spec["name"]
    _audit(session, "synced", admin_id=admin_id, panel=panel, product=product, data={"remote_template_id": row.remote_template_id, "changed": before})
    await session.commit()
    return {"remote_template_id": row.remote_template_id, "changed": before, "in_sync": True}


async def unlink(session: AsyncSession, panel: Panel, product: Product, *, admin_id: uuid.UUID) -> None:
    """Forget the mapping (the template stays on the panel). New prepaid renewals of this package stop being offered."""
    row = await mapping_for(session, panel.id, product.id)
    if row is None:
        return
    remote_id = row.remote_template_id
    await session.delete(row)
    _audit(session, "unlinked", admin_id=admin_id, panel=panel, product=product, data={"remote_template_id": remote_id})
    await session.commit()


async def set_disabled(session: AsyncSession, panel: Panel, product: Product, disabled: bool, *, admin_id: uuid.UUID) -> None:
    """Disable/enable a MANAGED template on the panel (a disabled template cannot be applied to accounts)."""
    row = await mapping_for(session, panel.id, product.id)
    if row is None:
        raise AppError("TEMPLATE_NOT_MAPPED", "برای این پکیج هنوز تمپلیتی ثبت نشده است.", 404)
    if not row.managed:
        raise AppError("TEMPLATE_NOT_MANAGED", "این تمپلیت دستی متصل شده و ملورین آن را تغییر نمی‌دهد.", 409)
    adapter = await _open(panel)
    try:
        await adapter.set_template_disabled(row.remote_template_id, disabled)
    except PanelError as exc:
        raise _panel_error(exc) from exc
    finally:
        await _close(adapter)
    _audit(session, "disabled" if disabled else "enabled", admin_id=admin_id, panel=panel, product=product, data={"remote_template_id": row.remote_template_id})
    await session.commit()
