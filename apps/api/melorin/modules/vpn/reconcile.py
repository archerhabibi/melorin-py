"""Reconcile v2 (PG-04): compare Melorin's accounts with ONE batched read of the panel instead of one call per account.

Per panel and run:

1. read every panel user (``AccountListing``, paged) into a dict; fall back to one call per account when the panel cannot list;
2. take the accounts that have waited longest (``last_synced_at ASC``, never-synced first), so every account gets its turn even
   when there are more than ``BATCH``;
3. per account: mirror the panel's state (:mod:`sync`), then open / refresh / auto-close its issues
   (``missing_on_panel``, ``panel_unreachable``, ``owner_mismatch``, ``limits_mismatch``);
4. panel users Melorin does not know become ``panel_orphans`` (listed for an admin, never deleted).

Nothing here writes to the panel.
"""

import datetime as dt
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core.db import utcnow
from melorin.kernel.models.stores import Store
from melorin.kernel.models.vpn import Panel, PanelAdmin, PanelOrphan, VpnAccount
from melorin.modules.vpn import issues, notices, sync
from melorin.modules.vpn.adapters.base import PanelAccount, PanelError, supports
from melorin.modules.vpn.adapters.registry import build_adapter, seed_adapter

log = logging.getLogger("melorin.vpn.reconcile")

BATCH = 1000  # accounts compared per panel per run
PAGE = 200  # panel users per request
MAX_PAGES = 100  # 20,000 panel users: beyond that the listing is treated as incomplete (no "missing" / orphan verdicts)
IN_CHUNK = 500


@dataclass
class PanelResult:
    panel_id: uuid.UUID
    checked: int = 0
    updated: int = 0  # accounts whose status changed
    missing: int = 0
    owner_mismatch: int = 0
    limits_mismatch: int = 0
    orphans: int = 0
    unreachable: bool = False
    complete: bool = True
    errors: list[str] = field(default_factory=list)


async def _remote_map(adapter) -> tuple[dict[str, PanelAccount], bool]:
    """Every panel user by username and whether the listing is complete."""
    out: dict[str, PanelAccount] = {}
    for page in range(MAX_PAGES):
        rows, total = await adapter.list_accounts(offset=page * PAGE, limit=PAGE)
        for row in rows:
            out[row.username] = row
        if len(rows) < PAGE or (total is not None and len(out) >= total):
            return out, True
    return out, False


async def _expected_owners(session: AsyncSession, panel_id: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = await session.execute(
        select(PanelAdmin.store_id, PanelAdmin.username).where(PanelAdmin.panel_id == panel_id, PanelAdmin.status == "active")
    )
    return {store_id: username for store_id, username in rows.all()}


async def _due_accounts(session: AsyncSession, panel_id: uuid.UUID, limit: int) -> list[VpnAccount]:
    return list(
        (
            await session.scalars(
                select(VpnAccount)
                .where(VpnAccount.panel_id == panel_id, VpnAccount.status.in_(sync.SYNCABLE), VpnAccount.archived_at.is_(None))
                .order_by(VpnAccount.last_synced_at.asc().nulls_first(), VpnAccount.created_at.asc())
                .limit(limit)
            )
        ).all()
    )


async def _store_levels(session: AsyncSession, accounts: list[VpnAccount]) -> dict[uuid.UUID, tuple[int, ...]]:
    """Each store's traffic-warning levels, read once per run (one query, not one per account)."""
    ids = {a.store_id for a in accounts if a.store_id}
    if not ids:
        return {}
    rows = (await session.execute(select(Store.id, Store.vpn_notice_settings).where(Store.id.in_(ids)))).all()
    return {sid: notices.levels_for_store(cfg) for sid, cfg in rows}


async def _compare(
    session, account, remote: PanelAccount | None, owners, now, result: PanelResult, levels: dict | None = None
) -> None:
    if remote is None:
        account.sync_error_count = int(account.sync_error_count or 0) + 1
        await issues.open_issue(session, account.id, issues.MISSING, {"username": account.username}, now=now)
        await issues.close_issues(session, [account.id], [issues.UNREACHABLE], now=now)
        result.missing += 1
        return
    drift = sync.limits_drift(account, remote)
    changes = await sync.apply_remote(session, account, remote, now=now, levels=(levels or {}).get(account.store_id))
    if changes:
        result.updated += 1
    await issues.close_issues(session, [account.id], [issues.MISSING, issues.UNREACHABLE], now=now)
    if drift:
        await issues.open_issue(session, account.id, issues.LIMITS_MISMATCH, drift, now=now)
        result.limits_mismatch += 1
    expected = owners.get(account.store_id)
    if expected and remote.owner and remote.owner != expected:
        await issues.open_issue(session, account.id, issues.OWNER_MISMATCH, {"expected": expected, "panel": remote.owner}, now=now)
        result.owner_mismatch += 1
    else:
        await issues.close_issues(session, [account.id], [issues.OWNER_MISMATCH], now=now)


async def _record_orphans(session, panel_id, remote: dict[str, PanelAccount], now) -> int:
    names = list(remote)
    known: set[str] = set()
    for i in range(0, len(names), IN_CHUNK):
        known.update((await session.scalars(select(VpnAccount.username).where(VpnAccount.username.in_(names[i : i + IN_CHUNK])))).all())
    existing = {o.username: o for o in (await session.scalars(select(PanelOrphan).where(PanelOrphan.panel_id == panel_id))).all()}
    open_now = 0
    for name, acc in remote.items():
        if name in known:
            continue
        row = existing.get(name)
        if row is None:
            row = PanelOrphan(
                panel_id=panel_id, username=name, first_seen_at=now, status="open"
            )  # explicit: the column default only applies at flush
            session.add(row)
            existing[name] = row
        elif row.status == "gone":
            row.status = "open"
        row.remote_id = int(acc.ref) if str(acc.ref).isdigit() else None
        row.remote_status, row.owner_username = acc.remote_status, acc.owner
        row.expire_at, row.traffic_limit_bytes, row.traffic_used_bytes = acc.expire_at, acc.traffic_limit_bytes, acc.traffic_used_bytes
        row.last_seen_at = now
        if row.status == "open":
            open_now += 1
    for name, row in existing.items():
        if row.status in ("open", "ignored") and (name not in remote or name in known):
            row.status = "gone"  # deleted on the panel, or Melorin now knows it
    return open_now


async def reconcile_panel(session: AsyncSession, panel: Panel, *, batch: int = BATCH, now: dt.datetime | None = None) -> PanelResult:
    """One reconcile pass over ``panel``. Commits. Never raises for a panel problem: that becomes ``panel_unreachable`` issues."""
    now = now or utcnow()
    panel_id = panel.id  # read once: after the rollback below ``panel`` is expired and an async session cannot lazy-load it
    result = PanelResult(panel_id=panel_id)
    accounts = await _due_accounts(session, panel_id, batch)
    adapter = None
    try:
        adapter = build_adapter(panel)
        listing = supports(adapter, "account_listing")
        remote: dict[str, PanelAccount] = {}
        complete = False
        if listing:
            remote, complete = await _remote_map(adapter)
        result.complete = complete
        owners = await _expected_owners(session, panel_id)
        levels = await _store_levels(session, accounts)
        for account in accounts:
            if listing and complete:
                found = remote.get(account.username)
            else:  # no listing (or a truncated one): ask for this one account, so "missing" is never guessed
                found = await seed_adapter(adapter, account).get_account(account.username)
            await _compare(session, account, found, owners, now, result, levels)
            result.checked += 1
        if listing and complete:
            result.orphans = await _record_orphans(session, panel_id, remote, now)
    except PanelError as exc:
        result.unreachable = True
        result.errors.append(exc.message[:200])
        await session.rollback()
        accounts = await _due_accounts(session, panel_id, batch)
        for account in accounts:
            account.sync_error_count = int(account.sync_error_count or 0) + 1
            await issues.open_issue(session, account.id, issues.UNREACHABLE, {"error": exc.message[:300]}, now=now)
        result.checked = len(accounts)
    finally:
        if adapter is not None:
            try:
                close = adapter.close()
                if hasattr(close, "__await__"):
                    await close
            except Exception:
                log.warning("reconcile: adapter close failed panel=%s", panel_id, exc_info=True)
    await session.commit()
    return result


async def reconcile_account(session: AsyncSession, account_id: uuid.UUID) -> str:
    """One account, on demand (admin action / retry). Returns ``ok | updated | issue | missing``."""
    account = await session.get(VpnAccount, account_id)
    if not account or not account.panel_id:
        return "missing"
    panel = await session.get(Panel, account.panel_id)
    adapter = seed_adapter(build_adapter(panel), account)
    now = utcnow()
    result = PanelResult(panel_id=panel.id)
    try:
        remote = await adapter.get_account(account.username)
    except PanelError as exc:
        account.sync_error_count = int(account.sync_error_count or 0) + 1
        await issues.open_issue(session, account.id, issues.UNREACHABLE, {"error": exc.message[:300]}, now=now)
        await session.commit()
        return "issue"
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            try:
                res = close()
                if hasattr(res, "__await__"):
                    await res
            except Exception:
                log.warning("reconcile: adapter close failed account=%s", account_id, exc_info=True)
    await _compare(session, account, remote, await _expected_owners(session, panel.id), now, result)
    await session.commit()
    if result.missing:
        return "issue"
    return "updated" if result.updated else "ok"
