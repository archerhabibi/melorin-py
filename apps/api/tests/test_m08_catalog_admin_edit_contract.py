from pathlib import Path

ROOT = Path(__file__).parents[1]
ROUTER = (ROOT / "melorin/modules/admin/router.py").read_text()


def test_bundle_edit_keeps_member_stats_and_can_clear_limit():
    block = ROUTER[ROUTER.index("async def update_bundle"):ROUTER.index("async def set_bundle_store")]
    assert 'k == "sales_limit"' in block  # explicit null = unlimited
    assert "delete(BundleMember)" not in block  # members are synced, not recreated
    assert "existing[pid].sort = i" in block


def test_product_patch_can_clear_optional_fields_and_guards_duplicate_code():
    block = ROUTER[ROUTER.index("async def update_product"):ROUTER.index("async def set_availability")]
    assert '"max_devices"' in block and "exclude_unset=True" in block
    assert "PRODUCT_CODE_EXISTS" in block


def test_availability_has_get_endpoint_matching_admin_web_contract():
    block = ROUTER[ROUTER.index("async def get_availability"):ROUTER.index("async def set_availability")]
    assert '@router.get("/products/{product_id}/availability"' in ROUTER
    for key in ('"store_id"', '"enabled"', '"listed"', '"customer_price"'):
        assert key in block
    assert "NotFound" in block
