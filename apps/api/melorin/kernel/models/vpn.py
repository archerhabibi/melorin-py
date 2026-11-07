import datetime as dt
import uuid

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, text
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
