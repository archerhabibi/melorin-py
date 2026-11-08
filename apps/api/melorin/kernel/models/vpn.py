import datetime as dt
import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
    true,
)
from sqlalchemy import event
from sqlalchemy.orm import Mapped, mapped_column

from melorin.kernel.base import Base, CreatedMixin, IdMixin, TimestampMixin


class Panel(IdMixin, TimestampMixin, Base):
    __tablename__ = "panels"
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))  # sanaei | pasarguard | mock
    base_url: Mapped[str] = mapped_column(String(300))
    credentials_enc: Mapped[str | None] = mapped_column(Text)  # encrypted JSON {username,password,...}
    config: Mapped[dict | None] = mapped_column(JSON)  # inbound ids, protocol options
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    health_status: Mapped[str] = mapped_column(String(20), default="unknown")
    last_health_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_health_error: Mapped[str | None] = mapped_column(Text)
    # PG-00: what this connection can do (adapter declaration narrowed by the panel role); see modules/vpn/capabilities.py
    capabilities: Mapped[dict | None] = mapped_column(JSON)
    capabilities_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # PG-01: node-level health summary (counts, reasons, ``sellable``); ``health_status`` is healthy | degraded | unhealthy | unknown
    health_detail: Mapped[dict | None] = mapped_column(JSON)
    # PG-03: the panel pushes events to ``/webhooks/pasarguard/{panel_id}``. The shared secret is encrypted at rest and shown to nobody;
    # ``webhook_last_at`` is the last accepted delivery (silence detection), ``webhook_connected_at`` when an admin switched it on.
    webhook_secret_enc: Mapped[str | None] = mapped_column(Text)
    webhook_last_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    webhook_connected_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # PG-13: last subscription test ({ok, checks: [...], expected, actual}); NULL = never run
    subscription_check: Mapped[dict | None] = mapped_column(JSON)
    subscription_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # PG-14: last live reading of the panel (resources, users by status, online, API latency) taken by ``panel_metrics_job``; the
    # /metrics scrape renders from this row so a scrape never waits for a panel.
    metrics_snapshot: Mapped[dict | None] = mapped_column(JSON)
    metrics_snapshot_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # PG-15: what the panel's settings should look like for Melorin to work (read-only comparison) and the last verdict.
    # ``expired_cleanup_policy``: keep = the panel must NOT auto-delete expired users | aligned = it may, but only after Melorin's renewal grace.
    expired_cleanup_policy: Mapped[str] = mapped_column(String(10), default="keep", server_default="keep")
    settings_drift: Mapped[dict | None] = mapped_column(JSON)
    settings_drift_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # Phase 6 (decision 2): with policy ``aligned`` the panel may auto-delete expired users only after THIS many days (NULL = the renewal
    # grace). Melorin keeps the expectation and warns on drift; it never writes the panel's setting.
    expected_retention_days: Mapped[int | None] = mapped_column(Integer)


class Server(IdMixin, TimestampMixin, Base):
    __tablename__ = "servers"
    name: Mapped[str] = mapped_column(String(100))
    panel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("panels.id"), index=True)
    location: Mapped[str | None] = mapped_column(String(100))
    capacity: Mapped[int] = mapped_column(Integer, default=500)
    product_codes: Mapped[list | None] = mapped_column(JSON)  # None = all products
    allow_test: Mapped[bool] = mapped_column(Boolean, default=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Where on the panel this slot sends new accounts: {"group_ids": [..]} | {"user_template_id": n[, "limits_from": ..]} |
    # {"inbound_ids": [..]}. NULL = inherit panel.config (the pre-target behaviour). Merged over panel.config at create time only.
    target: Mapped[dict | None] = mapped_column(JSON)
    last_assigned_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))  # round_robin key; written once per new order
    # PG-08: the destination's REAL state on the panel (group/host/node), refreshed by the health job. ``sellable`` is the sell-guard:
    # False removes this destination from new-order selection (existing accounts are untouched). A check that could not run keeps the old value.
    sellable: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    sellable_reason: Mapped[str | None] = mapped_column(String(300))
    destination_health: Mapped[dict | None] = mapped_column(JSON)  # status healthy|degraded|blocked, score, reasons, hosts/nodes counts
    panel_total_users: Mapped[int | None] = mapped_column(Integer)  # users the PANEL counts in this destination (single-group targets only)
    capacity_source: Mapped[str] = mapped_column(String(10), default="melorin", server_default="melorin")  # melorin | panel
    capacity_alert_level: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )  # highest announced fill threshold: 0 | 80 | 95 | 100
    capacity_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class VpnAccount(IdMixin, TimestampMixin, Base):
    __tablename__ = "vpn_accounts"
    username: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("products.id"))
    server_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("servers.id"), index=True)
    panel_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("panels.id"))
    panel_ref: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), index=True)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    traffic_limit_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    traffic_used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    subscription_url: Mapped[str | None] = mapped_column(Text)
    links: Mapped[list | None] = mapped_column(JSON)
    near_expiry_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    # PG-06: highest "traffic running low" threshold (percent) already announced for the current package; 0 = none. Reset on renewal.
    traffic_notified_level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # PG-02: what the panel last said (the panel is the source of truth for these; ``status`` is the normalised Melorin view)
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    remote_status: Mapped[str | None] = mapped_column(String(20))  # raw panel status: active|on_hold|limited|expired|disabled
    online_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    lifetime_used_traffic: Mapped[int | None] = mapped_column(BigInteger)
    sync_error_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # PG-09: a prepaid package queued on the panel (``next_plan``): {"template_id", "product_id", "order_id", "queued_at"}; None = nothing queued.
    queued_plan: Mapped[dict | None] = mapped_column(JSON)
    # Immutable snapshot written once at creation (audit/support only, NEVER a routing source: that is server_id/panel_id).
    placement: Mapped[dict | None] = mapped_column(JSON)


class AccountReturn(IdMixin, CreatedMixin, Base):
    """A customer's return (مرجوعی) of one purchased account. One row per order (unique), also the daily-limit ledger."""

    __tablename__ = "account_returns"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id"), unique=True)
    vpn_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vpn_accounts.id"), index=True)
    used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)  # usage at the moment of the return
    limit_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    amount: Mapped[int] = mapped_column(BigInteger, default=0)  # refunded to the customer's wallet of this store


class ProvisioningAttempt(IdMixin, CreatedMixin, Base):
    __tablename__ = "provisioning_attempts"
    __table_args__ = (UniqueConstraint("order_id", "attempt_no"),)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id"), index=True)
    vpn_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vpn_accounts.id"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))  # create | extend
    status: Mapped[str] = mapped_column(String(20))  # running | succeeded | failed
    error_kind: Mapped[str | None] = mapped_column(String(20))  # transient | permanent | unknown
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ReconciliationIssue(IdMixin, CreatedMixin, Base):
    """One discrepancy between Melorin and a panel (PG-04).

    Kinds: ``missing_on_panel`` | ``panel_unreachable`` | ``owner_mismatch`` | ``limits_mismatch``. At most ONE open row per
    (account, kind): a repeat only bumps ``occurrences``/``last_seen_at``. A row closes itself (``resolution='auto'``) when the
    condition clears, or by an admin (``resolved`` | ``ignored`` + reason).
    """

    __tablename__ = "reconciliation_issues"
    __table_args__ = (
        Index(
            "uq_reconciliation_issue_open",
            "vpn_account_id",
            "kind",
            unique=True,
            postgresql_where=text("status = 'open'"),
            sqlite_where=text("status = 'open'"),
        ),
    )
    vpn_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vpn_accounts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    details: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved | ignored
    occurrences: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(String(300))  # auto | duplicate | <admin action / reason>


class PanelNode(IdMixin, TimestampMixin, Base):
    """Last known state of one node of a panel (PG-01), refreshed by ``panel_node_sync_job``."""

    __tablename__ = "panel_nodes"
    __table_args__ = (UniqueConstraint("panel_id", "remote_id", name="uq_panel_nodes_panel_remote"),)
    panel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("panels.id", ondelete="CASCADE"), index=True)
    remote_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), index=True)  # connected | connecting | error | disabled | limited | unknown
    message: Mapped[str | None] = mapped_column(Text)  # the panel's error text (e.g. CERTIFICATE_VERIFY_FAILED)
    xray_version: Mapped[str | None] = mapped_column(String(40))
    usage_coefficient: Mapped[float | None] = mapped_column(Float)
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))  # last time the node was ``connected``
    status_changed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))  # gone from the panel's node list


class PanelOrphan(IdMixin, TimestampMixin, Base):
    """A user that exists on the panel but not in Melorin (PG-04). Listed for an admin; NEVER deleted automatically."""

    __tablename__ = "panel_orphans"
    __table_args__ = (UniqueConstraint("panel_id", "username", name="uq_panel_orphans_panel_username"),)
    panel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("panels.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(128))
    remote_id: Mapped[int | None] = mapped_column(Integer)
    remote_status: Mapped[str | None] = mapped_column(String(20))
    owner_username: Mapped[str | None] = mapped_column(String(64))  # the panel admin that owns the user
    expire_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    traffic_limit_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    traffic_used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open | ignored | gone
    note: Mapped[str | None] = mapped_column(String(300))
    first_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class PanelEvent(IdMixin, CreatedMixin, Base):
    """One event the panel pushed to Melorin (PG-03). Audit trail AND work queue: the endpoint only stores it (fast 200), the worker
    processes it. ``dedup_key`` is unique per panel, so a retried or replayed delivery is stored once and acts once.

    The payload is kept WITHOUT anything a leak could abuse (subscription links, proxy settings): see ``panel_events.sanitize``.
    The event is only a *trigger*: processing re-reads the account from the panel, so a stale or out-of-order event cannot
    write wrong state."""

    __tablename__ = "panel_events"
    __table_args__ = (
        UniqueConstraint("panel_id", "dedup_key", name="uq_panel_events_dedup"),
        Index("ix_panel_events_queue", "status", "available_at"),
    )
    panel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("panels.id", ondelete="CASCADE"), index=True)
    dedup_key: Mapped[str] = mapped_column(String(200))
    event_id: Mapped[str | None] = mapped_column(String(100))  # the panel's own id (stable across its retries) when it sends one
    action: Mapped[str] = mapped_column(String(40))
    username: Mapped[str | None] = mapped_column(String(128))
    enqueued_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))  # the panel's clock
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | processing | processed | ignored | failed
    available_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))  # next attempt (backoff)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(200))  # what happened: "active->limited", "unknown_account", an error text ...
    vpn_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("vpn_accounts.id", ondelete="SET NULL"))
    payload: Mapped[dict | None] = mapped_column(JSON)


@event.listens_for(VpnAccount.user_id, "set")
def _forbid_owner_change(target, value, oldvalue, initiator):
    """V1.1: VPN Account ownership transfer is forbidden for customers AND Admin."""
    from sqlalchemy.orm.base import NO_VALUE, NEVER_SET

    if oldvalue in (NO_VALUE, NEVER_SET, None) or oldvalue == value:
        return value
    raise ValueError("VPN account ownership transfer is not allowed")


class PanelAdmin(IdMixin, TimestampMixin, Base):
    """The PasarGuard admin (role Operator) that owns every account of ONE store on ONE panel.

    One row per (panel, store): the Main Store and every reseller store each get their own admin, and all accounts sold through
    that store (the reseller's own and their customers') are created under it. ``profile`` is the optional "Profile & contact"
    block; only the Melorin admin edits it (a reseller files a ``PanelAdminChangeRequest``)."""

    __tablename__ = "panel_admins"
    __table_args__ = (
        UniqueConstraint("panel_id", "store_id", name="uq_panel_admins_panel_store"),
        # Two stores can never share one panel login: a name clash would hand one store's accounts to the other's admin.
        Index("uq_panel_admins_panel_username", "panel_id", "username", unique=True),
    )
    panel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("panels.id"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    username: Mapped[str] = mapped_column(String(34))
    password_enc: Mapped[str | None] = mapped_column(Text)  # encrypted; the panel only keeps a hash
    remote_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending | active | error
    last_error: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    adopted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))  # pre-existing accounts moved under this admin
    profile: Mapped[dict | None] = mapped_column(JSON)  # profile_title, support_url, telegram_id, discord_webhook, sub_domain, note
    profile_synced: Mapped[bool] = mapped_column(Boolean, default=True)  # False = a profile edit still has to reach the panel
    # PG-12 governance. ``data_limit_bytes`` is the traffic ceiling Melorin asked for (NULL = not managed, 0 = unlimited);
    # the rest is what the panel last reported for this admin.
    data_limit_bytes: Mapped[int | None] = mapped_column(BigInteger)
    remote_status: Mapped[str | None] = mapped_column(String(12))  # the panel's admin status: active | disabled
    used_traffic_bytes: Mapped[int | None] = mapped_column(BigInteger)
    total_users: Mapped[int | None] = mapped_column(Integer)
    usage_checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    governance_error: Mapped[str | None] = mapped_column(String(300))


class PanelAdminChangeRequest(IdMixin, TimestampMixin, Base):
    """A reseller asks the admin to change its "Profile & contact"; the admin applies (optionally edited) or rejects it."""

    __tablename__ = "panel_admin_change_requests"
    __table_args__ = (
        # "One pending request per store" is enforced by the database, not only by a count (two concurrent clicks cannot both win).
        Index(
            "uq_panel_admin_request_one_pending",
            "store_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stores.id"), index=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    changes: Mapped[dict] = mapped_column(JSON)
    message: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)  # pending | applied | rejected | cancelled
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(String(500))


class ProductTemplate(IdMixin, TimestampMixin, Base):
    """PG-09: which panel user template carries a package (product) on one panel. ``managed`` = Melorin created it and may edit it."""

    __tablename__ = "product_templates"
    panel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("panels.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("products.id", ondelete="CASCADE"), index=True)
    remote_template_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(120))
    managed: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("panel_id", "product_id", name="uq_product_templates_panel_product"),)


class BulkOperation(IdMixin, TimestampMixin, Base):
    """One bulk operation over many accounts of ONE panel (PG-11): preview -> typed confirmation -> chunked run -> report.

    ``status``: ``previewed`` (items planned, nothing sent) -> ``confirmed`` (queued for the runner) -> ``running`` ->
    ``done`` | ``partial`` (some items failed, resumable) | ``failed`` | ``cancelled`` | ``expired`` (preview never confirmed).
    The selection is frozen into ``bulk_operation_items`` at preview time, so what an admin confirmed is exactly what runs."""

    __tablename__ = "bulk_operations"
    __table_args__ = (Index("ix_bulk_operations_status_created", "status", "created_at"),)
    panel_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("panels.id", ondelete="CASCADE"), index=True)
    store_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("stores.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # disable | enable | reset_usage | rotate_links | extend_days | add_traffic
    params: Mapped[dict | None] = mapped_column(JSON)  # {"days": 3} / {"gb": 5}
    selection: Mapped[dict | None] = mapped_column(JSON)  # the filter the admin used (audit)
    reason: Mapped[str | None] = mapped_column(String(300))
    origin: Mapped[str] = mapped_column(String(20), default="admin")  # admin | store_state
    status: Mapped[str] = mapped_column(String(12), default="previewed", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    sample: Mapped[list | None] = mapped_column(JSON)  # first usernames, for the preview
    error: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))  # an unconfirmed preview dies here
    lease_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))  # one runner at a time (crash-safe lease)


class BulkOperationItem(IdMixin, CreatedMixin, Base):
    """One account of a bulk operation. ``target`` is the ABSOLUTE value to write (new expiry / new traffic limit), computed once at
    preview time, so a retried item can never apply twice."""

    __tablename__ = "bulk_operation_items"
    __table_args__ = (UniqueConstraint("operation_id", "vpn_account_id", name="uq_bulk_items_operation_account"),)
    operation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("bulk_operations.id", ondelete="CASCADE"), index=True)
    vpn_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vpn_accounts.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(64))
    panel_ref: Mapped[str | None] = mapped_column(String(200))
    target: Mapped[dict | None] = mapped_column(JSON)  # {"expire_at": iso, "traffic_bytes": n}
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)  # pending | done | failed | skipped
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(300))
    done_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
