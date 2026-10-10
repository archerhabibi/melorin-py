from pathlib import Path

ROOT = Path(__file__).parents[1] / "melorin"


def test_notification_endpoints_are_user_scoped_and_wired():
    r = (ROOT / "modules/notifications/router.py").read_text()
    assert r.count("Notification.user_id == user.id") >= 3 and "n.user_id != user.id" in r
    assert "notifications_router" in (ROOT / "app.py").read_text()


def test_admin_receipt_is_private_and_audited():
    r = (ROOT / "modules/admin/router.py").read_text()
    assert '"/payments/{payment_id}/receipt"' in r and "payment.receipt_viewed" in r and "no-store" in r
