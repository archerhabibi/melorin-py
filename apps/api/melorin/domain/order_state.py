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


def set_vpn_status(account, dst: VpnStatus) -> None:
    """The one way to change ``account.status``: checks the lifecycle table, then assigns."""
    assert_vpn_transition(str(account.status), str(dst))
    account.status = dst
