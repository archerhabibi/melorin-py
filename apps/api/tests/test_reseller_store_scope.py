from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[1]


def test_reseller_application_is_store_scoped():
    model = read_source(ROOT / "melorin/modules/stores/models.py")
    router = read_source(ROOT / "melorin/modules/reseller/router.py")
    admin = read_source(ROOT / "melorin/modules/admin/router.py")
    assert "parent_store_id" in model
    assert "target_store_id" in model
    assert "STORE_MEMBERSHIP_REQUIRED" in router
    assert "target_store_id" in router
    assert "parent_store_id == target.id" in admin


def test_reseller_cost_uses_the_owner_main_store_customer_wallet():
    source = read_source(ROOT / "melorin/modules/orders/service.py")
    assert "wallet.get_wallet(session, order.user_id, store.id" in source
    assert "reseller_credit" not in source
    assert "store.owner_user_id, main.id" in source
    assert "await wallet.lock_wallets(session, to_lock)" in source
    assert "order.reseller_cost" in source
