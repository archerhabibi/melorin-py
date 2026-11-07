"""PasarGuard events (PG-03): store fast, process safely.

Two halves, deliberately separate:

* :func:`ingest` - called by the public endpoint. Stores every event once (UNIQUE ``(panel_id, dedup_key)``), so a replayed or
  retried delivery is a no-op, and answers immediately. No panel call, no business logic.
* :func:`run_pending` - called by the worker (and best-effort right after ingest for latency). Claims pending events with a lease,
  **coalesces them per user** (ten events for one user cost ONE read of the panel), re-reads the account from the panel and
  mirrors it through the same code as reconcile (:mod:`sync`, :mod:`issues`). The payload is never trusted as state, so stale,
  duplicated or out-of-order events cannot write wrong data, and the hourly reconcile stays the safety net for lost events.

Nothing here writes to the panel and nothing deletes anything: ``user_deleted`` only opens a ``missing_on_panel`` issue.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from melorin.core import settings_store
from melorin.core.crypto import decrypt
from melorin.core.db import session_factory, utcnow
from melorin.core.metrics import inc
from melorin.domain.order_state import VpnStatus
from melorin.kernel.models.vpn import Panel, PanelEvent, VpnAccount
from melorin.modules.vpn import notices, reconcile, sync
from melorin.modules.vpn.adapters.base import ErrorKind, PanelError
from melorin.modules.vpn.adapters.pasarguard.events import USER_EVENTS, ParsedBody
from melorin.modules.vpn.adapters.registry import build_adapter, seed_adapter

log = logging.getLogger("melorin.vpn.panel_events")

PENDING, PROCESSING, PROCESSED, IGNORED, FAILED = "pending", "processing", "processed", "ignored", "failed"
BATCH = 200
LEASE = dt.timedelta(minutes=10)  # a worker that dies mid-batch: its claimed rows become pending again after this
MAX_ATTEMPTS = 5  # internal errors and permanent panel errors (auth, validation): a person has to look
# The panel being down or slow is not the event's fault: keep trying for hours (10 s, 30 s, 2 min, 10 min, then every 30 min), so an
# outage of an hour or two loses nothing. Only after that is it ``failed`` (admin: retry-failed; reconcile converges anyway).
PANEL_MAX_ATTEMPTS = 12
BACKOFF_SECONDS = (10, 30, 120, 600, 1800)
MAX_AGE = dt.timedelta(days=7)  # an event this old has nothing to add (the next reconcile mirrors the same state)
RETENTION = dt.timedelta(days=30)
UNKNOWN_ACCOUNT_RETRIES = 2  # an event can outrun Melorin's own commit of a brand-new account: look again shortly
UNKNOWN_ACCOUNT_DELAY = 30


@dataclass
class IngestResult:
    accepted: int = 0
    duplicates: int = 0
    ignored: int = 0
    rejected: int = 0
    event_ids: list[uuid.UUID] = field(default_factory=list)


def _initial_status(event, now: dt.datetime) -> tuple[str, str | None]:
    if event.action not in USER_EVENTS:
        return IGNORED, "unknown_action"
    if not event.username:
        return IGNORED, "no_username"
    if event.enqueued_at is not None and now - event.enqueued_at > MAX_AGE:
        return IGNORED, "stale"
    return PENDING, None


async def _existing_keys(session: AsyncSession, panel_id: uuid.UUID, keys: list[str]) -> set[str]:
    found: set[str] = set()
    for i in range(0, len(keys), 400):
        found.update(
            (
                await session.scalars(
                    select(PanelEvent.dedup_key).where(PanelEvent.panel_id == panel_id, PanelEvent.dedup_key.in_(keys[i : i + 400]))
                )
            ).all()
        )
    return found


async def ingest(session: AsyncSession, panel: Panel, parsed: ParsedBody, *, now: dt.datetime | None = None) -> IngestResult:
    """Store one delivery. Commits. Replays (same dedup key) are counted, not stored again."""
    now = now or utcnow()
    result = IngestResult(rejected=parsed.rejected)
    panel_id = panel.id
    unique: dict[str, object] = {}
    for event in parsed.events:
        if event.dedup_key in unique:
            result.duplicates += 1
            continue
        unique[event.dedup_key] = event
    known = await _existing_keys(session, panel_id, list(unique))
    rows: list[PanelEvent] = []
    for key, event in unique.items():
        if key in known:
            result.duplicates += 1
            continue
        status, outcome = _initial_status(event, now)
        rows.append(
            PanelEvent(
                id=uuid.uuid4(),
                panel_id=panel_id,
                dedup_key=key,
                event_id=event.event_id,
                action=event.action,
                username=event.username,
                enqueued_at=event.enqueued_at,
                received_at=now,
                status=status,
                available_at=now if status == PENDING else None,
                outcome=outcome,
                processed_at=now if status == IGNORED else None,
                payload=event.payload,
            )
        )
    stored = await _store(session, rows, result)
    for row in stored:
        if row.status == PENDING:
            result.accepted += 1
            result.event_ids.append(row.id)
        else:
            result.ignored += 1
        inc("melorin_panel_events_total", action=row.action if row.action in USER_EVENTS else "other", status="received")
    await session.execute(update(Panel).where(Panel.id == panel_id).values(webhook_last_at=now))
    await session.commit()
    return result


async def _store(session: AsyncSession, rows: list[PanelEvent], result: IngestResult) -> list[PanelEvent]:
    """Insert ``rows``; a concurrent delivery of the same event may win the unique index, which then counts as a duplicate."""
    if not rows:
        return []
    try:
        async with session.begin_nested():
            session.add_all(rows)
            await session.flush()
        return rows
    except IntegrityError:
        pass
    stored: list[PanelEvent] = []
    for row in rows:
        clone = PanelEvent(**{c.name: getattr(row, c.name) for c in PanelEvent.__table__.columns if c.name != "created_at"})
        try:
            async with session.begin_nested():
                session.add(clone)
                await session.flush()
            stored.append(clone)
        except IntegrityError:
            result.duplicates += 1
    return stored


# --------------------------------------------------------------------------------------------------------------- processing


@dataclass
class RunStats:
    claimed: int = 0
    processed: int = 0
    ignored: int = 0
    retried: int = 0
    failed: int = 0


async def claim(
    session: AsyncSession, *, limit: int = BATCH, panel_id: uuid.UUID | None = None, now: dt.datetime | None = None
) -> list[PanelEvent]:
    """Lease up to ``limit`` due events (oldest first). Rows another worker holds are skipped; abandoned leases are released."""
    now = now or utcnow()
    await session.execute(
        update(PanelEvent).where(PanelEvent.status == PROCESSING, PanelEvent.available_at <= now).values(status=PENDING, available_at=now)
    )
    query = select(PanelEvent).where(PanelEvent.status == PENDING, PanelEvent.available_at <= now)
    if panel_id is not None:
        query = query.where(PanelEvent.panel_id == panel_id)
    rows = list(
        (await session.scalars(query.order_by(PanelEvent.received_at, PanelEvent.id).limit(limit).with_for_update(skip_locked=True))).all()
    )
    for row in rows:
        row.status, row.available_at = PROCESSING, now + LEASE
    await session.commit()
    return rows


def _finish(rows: list[PanelEvent], status: str, outcome: str, now: dt.datetime, account_id: uuid.UUID | None = None) -> None:
    for row in rows:
        row.status, row.outcome, row.processed_at, row.available_at = status, outcome[:200], now, None
        if account_id is not None:
            row.vpn_account_id = account_id
        inc("melorin_panel_events_total", action=row.action if row.action in USER_EVENTS else "other", status=status)


def _retry(
    rows: list[PanelEvent], reason: str, now: dt.datetime, *, delay: int | None = None, max_attempts: int = MAX_ATTEMPTS
) -> tuple[int, int]:
    """Back off (or give up after ``max_attempts``). Returns (retried, failed). The last backoff step repeats."""
    retried = failed = 0
    for row in rows:
        row.attempts = int(row.attempts or 0) + 1
        row.outcome = reason[:200]
        if row.attempts >= max_attempts:
            row.status, row.processed_at, row.available_at = FAILED, now, None
            inc("melorin_panel_events_total", action=row.action if row.action in USER_EVENTS else "other", status=FAILED)
            failed += 1
        else:
            step = BACKOFF_SECONDS[min(row.attempts - 1, len(BACKOFF_SECONDS) - 1)]
            row.status, row.available_at = PENDING, now + dt.timedelta(seconds=delay if delay is not None else step)
            retried += 1
    return retried, failed


async def _near_expiry(session: AsyncSession, account: VpnAccount, now: dt.datetime) -> str | None:
    """``reached_days_left`` fires at the PANEL's thresholds; Melorin warns inside its own window, once per period."""
    if account.status != VpnStatus.ACTIVE or account.near_expiry_notified or account.expires_at is None:
        return None
    hours = int(await settings_store.get(session, "vpn.near_expiry_hours") or 48)
    expires = sync.aware(account.expires_at)
    if not now < expires <= now + dt.timedelta(hours=hours):
        return None
    account.near_expiry_notified = True  # same flag as near_expiry_job, reset by a renewal
    await notices.near_expiry(session, account)
    return "near_expiry"


def _panel_attempts(exc: PanelError) -> int:
    """Timeouts, 5xx and 'outcome unclear' are the panel's problem: retry for long. A permanent error needs a person."""
    return MAX_ATTEMPTS if exc.kind == ErrorKind.PERMANENT else PANEL_MAX_ATTEMPTS


async def _read_remote(adapter, account: VpnAccount, username: str):
    return await seed_adapter(adapter, account).get_account(username)


async def _handle_user(
    session: AsyncSession, panel: Panel, adapter, username: str, rows: list[PanelEvent], ctx: dict, now: dt.datetime
) -> tuple[int, int, int]:
    """All events of ONE user in this batch -> one re-read of the panel. Returns (processed, ignored, retried+failed).

    The panel is read WITHOUT holding the account's row lock (a slow panel must not freeze renewals and orders on that account for
    the length of a timeout). The lock is taken afterwards, and when the account changed in between (a renewal committed while we
    were reading) the read is repeated under the lock so a stale panel answer can never overwrite newer data.
    """
    account = await session.scalar(select(VpnAccount).where(VpnAccount.panel_id == panel.id, VpnAccount.username == username))
    if account is None:
        young = [r for r in rows if int(r.attempts or 0) < UNKNOWN_ACCOUNT_RETRIES]
        old = [r for r in rows if r not in young]
        _retry(young, "unknown_account (waiting for Melorin)", now, delay=UNKNOWN_ACCOUNT_DELAY)
        _finish(old, IGNORED, "unknown_account (reconcile lists it as a discovered user)", now)
        return 0, len(old), len(young)
    if account.status not in sync.SYNCABLE or account.archived_at is not None:
        _finish(rows, IGNORED, f"not_syncable:{account.status}", now, account.id)
        return 0, len(rows), 0
    seen = account.updated_at
    try:
        remote = await _read_remote(adapter, account, username)
        await session.refresh(account, with_for_update=True)  # lock only now: short, no network inside
        if account.updated_at != seen:
            remote = await _read_remote(adapter, account, username)  # rare: re-read under the lock
    except PanelError as exc:
        await session.refresh(account, with_for_update=True)
        account.sync_error_count = int(account.sync_error_count or 0) + 1
        retried, failed = _retry(rows, f"panel error: {exc.message}", now, max_attempts=_panel_attempts(exc))
        return 0, 0, retried + failed
    if account.status not in sync.SYNCABLE or account.archived_at is not None:  # changed while we were reading
        _finish(rows, IGNORED, f"not_syncable:{account.status}", now, account.id)
        return 0, len(rows), 0
    actions = {r.action for r in rows}
    result = reconcile.PanelResult(panel_id=panel.id)
    before = account.status
    # ``user_updated`` is usually Melorin's own renewal echoing back: do not raise a limits_mismatch for it (the hourly reconcile still does)
    check_drift = bool(actions - {"user_updated", "user_created"})
    await reconcile._compare(session, account, remote, ctx["owners"], now, result, ctx["levels"], check_drift=check_drift)
    notes: list[str] = []
    if remote is None:
        notes.append("missing_on_panel" if "user_deleted" in actions else "not_found_on_panel")
    else:
        if "user_deleted" in actions:
            notes.append("stale_delete_ignored")  # the user exists again: the delete event is history
        if account.status != before:
            notes.append(f"{before}->{account.status}")
        if "reached_days_left" in actions and (extra := await _near_expiry(session, account, now)):
            notes.append(extra)
    _finish(rows, PROCESSED, ", ".join(notes) or "synced", now, account.id)
    return len(rows), 0, 0


async def _process_panel(session: AsyncSession, panel_id: uuid.UUID, rows: list[PanelEvent], now: dt.datetime) -> RunStats:
    stats = RunStats(claimed=len(rows))
    panel = await session.get(Panel, panel_id)
    if panel is None or not panel.is_enabled:
        _finish(rows, IGNORED, "panel_disabled", now)
        stats.ignored = len(rows)
        await session.commit()
        return stats
    try:
        adapter = build_adapter(panel)
    except Exception as exc:  # misconfigured panel (TLS rule, unknown kind): retry later, never crash the sweep
        retried, failed = _retry(rows, f"adapter: {type(exc).__name__}", now, max_attempts=PANEL_MAX_ATTEMPTS)
        stats.retried, stats.failed = retried, failed
        await session.commit()
        return stats
    by_user: dict[str, list[PanelEvent]] = {}
    for row in rows:
        by_user.setdefault(row.username or "", []).append(row)
    try:
        owners = await reconcile._expected_owners(session, panel.id)
        accounts = list(
            (await session.scalars(select(VpnAccount).where(VpnAccount.panel_id == panel.id, VpnAccount.username.in_(list(by_user))))).all()
        )
        ctx = {"owners": owners, "levels": await reconcile._store_levels(session, accounts)}
        for username, group in by_user.items():
            try:
                async with session.begin_nested():
                    done, ignored, bad = await _handle_user(session, panel, adapter, username, group, ctx, now)
                stats.processed += done
                stats.ignored += ignored
                stats.retried += bad
            except Exception:
                log.warning("panel event failed panel=%s user=%s", panel_id, username, exc_info=True)
                for row in group:  # the savepoint rollback expired them; an async session cannot lazy-load
                    await session.refresh(row)
                retried, failed = _retry(group, "internal error", now)
                stats.retried, stats.failed = stats.retried + retried, stats.failed + failed
            await session.commit()  # one user at a time: a poison event never rolls back its neighbours
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            try:
                await close()
            except Exception:
                log.debug("adapter close failed", exc_info=True)
    await session.commit()
    return stats


async def run_pending(*, limit: int = BATCH, panel_id: uuid.UUID | None = None, now: dt.datetime | None = None, factory=None) -> RunStats:
    """One processing sweep. Safe to run from several workers at once (leased claims) and to call after every ingest."""
    now = now or utcnow()
    make = factory or session_factory()
    async with make() as session:
        rows = await claim(session, limit=limit, panel_id=panel_id, now=now)
    total = RunStats(claimed=len(rows))
    by_panel: dict[uuid.UUID, list[uuid.UUID]] = {}
    for row in rows:
        by_panel.setdefault(row.panel_id, []).append(row.id)
    for pid, ids in by_panel.items():
        async with make() as session:
            mine = list((await session.scalars(select(PanelEvent).where(PanelEvent.id.in_(ids)))).all())
            try:
                part = await _process_panel(session, pid, mine, now)
            except Exception:
                await session.rollback()
                log.warning("panel event sweep failed panel=%s", pid, exc_info=True)
                continue
        total.processed += part.processed
        total.ignored += part.ignored
        total.retried += part.retried
        total.failed += part.failed
    return total


async def purge(session: AsyncSession, *, now: dt.datetime | None = None) -> int:
    """Retention: finished events older than ``RETENTION`` go (audit is short-lived by design; accounts keep their own history)."""
    cutoff = (now or utcnow()) - RETENTION
    result = await session.execute(
        delete(PanelEvent).where(PanelEvent.status.in_((PROCESSED, IGNORED, FAILED)), PanelEvent.received_at < cutoff)
    )
    await session.commit()
    return int(result.rowcount or 0)


def secret_for(panel: Panel) -> str | None:
    """The panel's webhook secret in clear, or ``None`` (never connected / unreadable)."""
    if not panel.webhook_secret_enc:
        return None
    try:
        return decrypt(panel.webhook_secret_enc)
    except RuntimeError:
        return None
