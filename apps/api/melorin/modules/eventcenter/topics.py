"""Event Center topics (SRS §17). Each maps to one forum Topic (``message_thread_id``) of the destination group."""

PAYMENTS = "payments"
ORDERS = "orders"
DEBT = "debt"
TICKETS = "tickets"
ERRORS = "errors"

TOPICS: dict[str, str] = {
    PAYMENTS: "پرداخت‌ها",
    ORDERS: "سفارش‌ها",
    DEBT: "بدهی",
    TICKETS: "تیکت‌ها",
    ERRORS: "خطاها",
}

# Events an admin also wants to see for a reseller's store (prefixed with the store name). Everything else stays private
# to the store it belongs to: a reseller sees only his own events, and the admin is not flooded with every reseller sale.
ADMIN_COPY_TOPICS = frozenset({DEBT, ERRORS})
