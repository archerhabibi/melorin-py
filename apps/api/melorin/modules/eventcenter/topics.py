"""Event Center topics (SRS §17). Each maps to one forum Topic (``message_thread_id``) of the destination group."""

PAYMENTS = "payments"
ORDERS = "orders"
DEBT = "debt"
TICKETS = "tickets"
ERRORS = "errors"
DAILY = "daily"  # nightly summary of the last 24 hours
AFFILIATE = "affiliate"  # referrals and commissions (Main Store only)
TESTS = "tests"  # test accounts
BACKUP = "backup"  # platform backups (admin only)

TOPICS: dict[str, str] = {
    PAYMENTS: "پرداخت‌ها",
    ORDERS: "سفارش‌ها",
    DEBT: "بدهی",
    TICKETS: "تیکت‌ها",
    ERRORS: "خطاها",
    DAILY: "گزارش شبانه",
    AFFILIATE: "کمیسیون و معرف",
    TESTS: "اکانت تست",
    BACKUP: "پشتیبان‌گیری",
}

# Platform-level topics: only the Admin's group has them. A reseller never sees (or can configure) a backup of the platform,
# and the referral program exists only in the Main Store (docs/17), so a reseller's affiliate topic would stay empty forever.
ADMIN_ONLY_TOPICS = frozenset({BACKUP, AFFILIATE})

# Events an admin also wants to see for a reseller's store (prefixed with the store name). Everything else stays private
# to the store it belongs to: a reseller sees only his own events, and the admin is not flooded with every reseller sale.
ADMIN_COPY_TOPICS = frozenset({DEBT, ERRORS})


def topics_for(admin: bool) -> dict[str, str]:
    """The topics that exist for one kind of destination: all of them for the Admin, the store-level ones for a reseller."""
    return dict(TOPICS) if admin else {k: v for k, v in TOPICS.items() if k not in ADMIN_ONLY_TOPICS}
