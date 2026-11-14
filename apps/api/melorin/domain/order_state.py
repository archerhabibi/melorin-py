import dataclasses
from enum import StrEnum


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAYMENT_PENDING = "payment_pending"
    PAID = "paid"
    PROCESSING = "processing"
    PROVISIONING = "provisioning"
    COMPLETED = "completed"
    PAYMENT_FAILED = "payment_failed"
    PROVISIONING_FAILED = "provisioning_failed"
    MANUAL_REVIEW = "manual_review"
    CANCELLED = "cancelled"
    REFUND_PENDING = "refund_pending"
    REFUNDED = "refunded"


S = OrderStatus
TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    S.PENDING: {S.PAYMENT_PENDING, S.PAID, S.CANCELLED},
    S.PAYMENT_PENDING: {S.PAID, S.PAYMENT_FAILED, S.CANCELLED},
    S.PAYMENT_FAILED: {S.PAYMENT_PENDING, S.CANCELLED},
    S.PAID: {S.PROCESSING, S.REFUND_PENDING},
    S.PROCESSING: {S.PROVISIONING, S.PROVISIONING_FAILED, S.PAID},
    S.PROVISIONING: {S.COMPLETED, S.PROVISIONING_FAILED, S.PROCESSING},
    S.PROVISIONING_FAILED: {S.PROCESSING, S.MANUAL_REVIEW, S.REFUND_PENDING, S.COMPLETED},
    S.MANUAL_REVIEW: {S.PROCESSING, S.REFUND_PENDING, S.COMPLETED},
    S.COMPLETED: {S.REFUND_PENDING},
    S.REFUND_PENDING: {S.REFUNDED, S.MANUAL_REVIEW},
    S.CANCELLED: set(),
    S.REFUNDED: set(),
}

REFUNDABLE = {S.PAID, S.PROVISIONING_FAILED, S.MANUAL_REVIEW, S.COMPLETED}
RETRYABLE = {S.PROVISIONING_FAILED, S.MANUAL_REVIEW}


class InvalidTransition(Exception):
    def __init__(self, src: str, dst: str):
        super().__init__(f"{src} -> {dst}")
        self.src, self.dst = src, dst


def assert_transition(src: str, dst: str) -> None:
    if OrderStatus(dst) not in TRANSITIONS[OrderStatus(src)]:
        raise InvalidTransition(src, dst)


class VpnStatus(StrEnum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    LIMITED = "limited"  # PG-02: the panel stopped the account because its traffic quota is used up (renewable)
    REVOKED = "revoked"
    ARCHIVED = "archived"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    AWAITING_REVIEW = "awaiting_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


V = VpnStatus
VPN_TRANSITIONS: dict[VpnStatus, set[VpnStatus]] = {
    V.PENDING: {V.PROVISIONING, V.ACTIVE, V.REVOKED, V.ARCHIVED},
    V.PROVISIONING: {V.ACTIVE, V.PENDING, V.REVOKED, V.ARCHIVED},
    V.ACTIVE: {V.SUSPENDED, V.EXPIRED, V.LIMITED, V.REVOKED, V.ARCHIVED},
    V.SUSPENDED: {V.ACTIVE, V.EXPIRED, V.REVOKED, V.ARCHIVED},
    V.EXPIRED: {V.ACTIVE, V.REVOKED, V.ARCHIVED},  # renewal brings it back
    V.LIMITED: {V.ACTIVE, V.EXPIRED, V.SUSPENDED, V.REVOKED, V.ARCHIVED},  # quota reset / renewal
    V.REVOKED: {V.ARCHIVED},
    V.ARCHIVED: set(),
}


def assert_vpn_transition(src: str, dst: str) -> None:
    """Guard for account lifecycle changes (renewal, return, recreate, bulk, reconcile). Same state is a no-op."""
    if src == dst:
        return
    if VpnStatus(dst) not in VPN_TRANSITIONS[VpnStatus(src)]:
        raise InvalidTransition(src, dst)


class VpnSource(StrEnum):
    """WHO is changing an account's status. Every writer names itself so a transition can be audited and so a path can
    never write a status it has no business with (a bulk action cannot revoke, the expiry job cannot activate)."""

    PROVISIONING = "provisioning"  # an order creating/renewing the account on the panel (and cleaning a failed stub)
    PANEL_SYNC = "panel_sync"  # what the panel itself reports (read cycle, reconcile, webhook events)
    RECONCILIATION = "reconciliation"  # an admin resolving a discrepancy
    BULK = "bulk"  # admin bulk operation
    ACCOUNT_TOOLS = "account_tools"  # owner / store suspending or resuming one account
    EXPIRY_JOB = "expiry_job"  # Melorin's own clock for accounts without a panel reading
    RETURN = "return"  # the customer return (refund) revoking the account


SOURCE_TARGETS: dict[VpnSource, frozenset[VpnStatus]] = {
    VpnSource.PROVISIONING: frozenset({V.ACTIVE, V.ARCHIVED}),
    VpnSource.PANEL_SYNC: frozenset({V.ACTIVE, V.SUSPENDED, V.EXPIRED, V.LIMITED}),
    VpnSource.RECONCILIATION: frozenset({V.ARCHIVED}),
    VpnSource.BULK: frozenset({V.ACTIVE, V.SUSPENDED}),
    VpnSource.ACCOUNT_TOOLS: frozenset({V.ACTIVE, V.SUSPENDED}),
    VpnSource.EXPIRY_JOB: frozenset({V.EXPIRED}),
    VpnSource.RETURN: frozenset({V.REVOKED}),
}


class SourceNotAllowed(InvalidTransition):
    def __init__(self, src: str, dst: str, source: str):
        super().__init__(src, dst)
        self.source = source
        self.args = (f"{src} -> {dst} is not a status {source} may write",)


@dataclasses.dataclass(frozen=True)
class VpnTransition:
    """The outcome of one status write; ``changed`` is False for an idempotent repeat. Callers put it in their audit data."""

    src: str
    dst: str
    source: str
    changed: bool

    def as_audit(self) -> dict:
        return {"from": self.src, "to": self.dst, "source": self.source}


def set_vpn_status(account, dst: VpnStatus, *, source: VpnSource) -> VpnTransition:
    """The one way to change ``account.status``.

    Precondition: the lifecycle table allows ``current -> dst`` AND ``source`` may write ``dst``. Postcondition: the account holds
    ``dst``. Writing the state the account already has changes nothing (so a retried job or a replayed event is harmless)."""
    src = str(account.status)
    dst = VpnStatus(dst)
    source = VpnSource(source)
    if dst not in SOURCE_TARGETS[source]:
        raise SourceNotAllowed(src, str(dst), str(source))
    assert_vpn_transition(src, str(dst))
    changed = src != str(dst)
    if changed:
        account.status = dst
    assert str(account.status) == str(dst)
    return VpnTransition(src=src, dst=str(dst), source=str(source), changed=changed)
