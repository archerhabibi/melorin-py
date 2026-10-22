from pathlib import Path

from _source import read_source

ROOT = Path(__file__).parents[1] / "melorin"


def test_notification_endpoints_are_user_scoped_and_wired():
    r = read_source(ROOT / "modules/notifications/router.py")
    # R01: scoped by user AND store through the one StoreScope (no hand-written user checks in the router)
    assert r.count("StoreScope.of(ctx)") >= 3 and "StoreCtx" in r and "CurrentUser" not in r
    assert "notifications_router" in read_source(ROOT / "app.py")


def test_admin_receipt_is_private_and_audited():
    r = read_source(ROOT / "modules/admin/router.py")
    assert '"/payments/{payment_id}/receipt"' in r and "payment.receipt_viewed" in r and "no-store" in r
