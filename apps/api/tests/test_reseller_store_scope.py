from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_reseller_application_is_store_scoped():
    model = (ROOT / "melorin/modules/stores/models.py").read_text()
    router = (ROOT / "melorin/modules/reseller/router.py").read_text()
    admin = (ROOT / "melorin/modules/admin/router.py").read_text()
    assert "parent_store_id" in model
    assert "target_store_id" in model
    assert "STORE_MEMBERSHIP_REQUIRED" in router
    assert "target_store_id" in router
    assert "parent_store_id == target.id" in admin


def test_reseller_purchase_keeps_customer_and_credit_wallets_separate():
    source = (ROOT / "melorin/modules/orders/service.py").read_text()
    assert 'wallet.get_wallet(session, order.user_id, store.id' in source
    assert 'kind="reseller_credit"' in source
    assert "await wallet.lock_wallets(session, to_lock)" in source
    assert "order.reseller_cost" in source
