import uuid

from melorin.modules.vpn.allocation import Candidate, select_allocation


def cand(name, **kw):
    base = dict(
        server_id=uuid.uuid4(), server_name=name, panel_id=uuid.uuid4(), panel_name=f"P-{name}",
        server_enabled=True, panel_enabled=True, panel_healthy=True, allow_test=True,
        product_codes=(), capacity=10, active_on_server=0, active_on_panel=0,
    )
    base.update(kw)
    return Candidate(**base)


def test_wrong_product_code_is_rejected_with_reason():
    c = cand("ws", product_codes=("mmmm",))
    chosen, reasons = select_allocation([c], product_code="10", is_test=False)
    assert chosen is None
    assert reasons == ["ws: کد محصول 10 در لیست این سرور نیست"]


def test_empty_product_codes_accept_any_product():
    c = cand("all", product_codes=())
    chosen, _ = select_allocation([c], product_code="20", is_test=False)
    assert chosen is c


def test_direct_mode_prefers_least_loaded_server():
    busy = cand("busy", active_on_server=5)
    free = cand("free", active_on_server=1)
    chosen, _ = select_allocation([busy, free], product_code="10", is_test=False)
    assert chosen is free


def test_group_mode_prefers_least_loaded_panel_then_member_sort():
    a = cand("a", active_on_panel=3, member_sort=0)
    b = cand("b", active_on_panel=1, member_sort=5)
    chosen, _ = select_allocation([a, b], product_code="10", is_test=False, group_mode="automatic")
    assert chosen is b


def test_test_order_needs_allow_test():
    c = cand("no-test", allow_test=False)
    chosen, reasons = select_allocation([c], product_code="10", is_test=True)
    assert chosen is None and "تست" in reasons[0]


def test_unhealthy_or_disabled_servers_are_rejected():
    cands = [cand("sick", panel_healthy=False), cand("off", server_enabled=False), cand("pnl-off", panel_enabled=False)]
    chosen, reasons = select_allocation(cands, product_code="10", is_test=False)
    assert chosen is None and len(reasons) == 3


def test_full_server_is_rejected():
    c = cand("full", capacity=2, active_on_server=2)
    chosen, reasons = select_allocation([c], product_code="10", is_test=False)
    assert chosen is None and "ظرفیت" in reasons[0]


def test_member_sales_limit_excludes_member_in_group_mode():
    c = cand("capped", member_sales_limit=3, member_sold=3)
    chosen, reasons = select_allocation([c], product_code="10", is_test=False, group_mode="automatic")
    assert chosen is None and "سقف" in reasons[0]


def test_manual_group_only_uses_selected_panel():
    a = cand("a")
    b = cand("b")
    chosen, _ = select_allocation([a, b], product_code="10", is_test=False, group_mode="manual", selected_panel_id=b.panel_id)
    assert chosen is b


def test_product_default_group_is_the_bot_and_web_rule():
    # The rule lives in one place: a group-less purchase in direct mode and a group purchase share select_allocation.
    c = cand("only")
    direct, _ = select_allocation([c], product_code="10", is_test=False)
    grouped, _ = select_allocation([c], product_code="10", is_test=False, group_mode="automatic")
    assert direct is c and grouped is c


def test_group_policy_is_one_shared_rule():
    from types import SimpleNamespace

    from melorin.modules.vpn.allocation import group_policy_violation

    g = SimpleNamespace(is_enabled=True, sales_limit=None, sold_count=0, selection_mode="automatic")
    assert group_policy_violation(g, store_access_enabled=None, selected_panel_id=None) is None
    assert group_policy_violation(None, store_access_enabled=None, selected_panel_id=None)
    assert group_policy_violation(g, store_access_enabled=False, selected_panel_id=None)
    assert group_policy_violation(g, store_access_enabled=None, selected_panel_id=uuid.uuid4())  # automatic forbids a choice
    g.selection_mode = "manual"
    assert group_policy_violation(g, store_access_enabled=None, selected_panel_id=None)  # manual needs a choice
    g.sales_limit, g.sold_count = 2, 2
    assert group_policy_violation(g, store_access_enabled=None, selected_panel_id=uuid.uuid4())
