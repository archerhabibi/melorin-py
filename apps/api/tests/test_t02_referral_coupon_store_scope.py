"""T02: referrals and coupons never mix stores (docs/17-Referral-Coupon-Store-Scope.md)."""

import datetime as dt

from sqlalchemy import select

from _db import make_order, make_product, make_store, make_user, open_session
from melorin.core.db import utcnow
from melorin.modules.catalog import service as catalog
from melorin.kernel.models.catalog import Coupon
from melorin.modules.referral import service as referral
from melorin.kernel.models.referral import Commission, CommissionRule, ReferralRelationship


async def _world(s):
    referrer, referred = await make_user(s), await make_user(s)
    main = await make_store(s, kind="main")
    reseller = await make_store(s, kind="reseller", owner=await make_user(s))
    product = await make_product(s)
    s.add(ReferralRelationship(store_id=main.id, referrer_user_id=referrer.id, referred_user_id=referred.id))
    s.add(CommissionRule(store_id=main.id, kind="signup_reward", model="fixed", value=500, is_active=True))
    s.add(CommissionRule(store_id=reseller.id, kind="signup_reward", model="fixed", value=500, is_active=True))
    await s.commit()
    return referrer, referred, main, reseller, product


async def _complete(s, user, store, product):
    o = await make_order(s, user=user, store=store, product=product, status="completed")
    o.completed_at = utcnow()
    await s.commit()
    return o


async def test_a_purchase_in_another_store_never_pays_the_main_store_referrer():
    async with open_session() as s:
        referrer, referred, main, reseller, product = await _world(s)
        other = await _complete(s, referred, reseller, product)
        await referral.on_order_completed(s, other.id)
        await s.commit()
        assert (await s.scalars(select(Commission))).all() == []  # nothing paid, reseller's expense account untouched


async def test_a_purchase_in_the_store_the_referral_was_made_in_still_pays():
    async with open_session() as s:
        referrer, referred, main, reseller, product = await _world(s)
        order = await _complete(s, referred, main, product)
        await referral.on_order_completed(s, order.id)
        await s.commit()
        rows = (await s.scalars(select(Commission))).all()
        assert len(rows) == 1 and rows[0].store_id == main.id and rows[0].referrer_user_id == referrer.id and rows[0].amount == 500


async def test_first_purchase_is_counted_in_the_referral_store_only():
    async with open_session() as s:
        referrer, referred, main, reseller, product = await _world(s)
        other = await _complete(s, referred, reseller, product)  # earlier purchase in another store: pays nothing
        other.completed_at = utcnow() - dt.timedelta(days=1)
        await s.commit()
        order = await _complete(s, referred, main, product)
        await referral.on_order_completed(s, order.id)
        await s.commit()
        rows = (await s.scalars(select(Commission))).all()
        assert len(rows) == 1 and rows[0].kind == "signup_reward" and rows[0].store_id == main.id


async def _coupon(s, *, owner_key, store_id, code="SAVE", scope="store"):
    c = Coupon(code=code, owner_key=owner_key, store_id=store_id, scope=scope, creator_type="admin", percent_bp=1000, per_customer_limit=1)
    s.add(c)
    await s.flush()
    return c


async def test_store_coupon_wins_and_only_the_winner_is_looked_up_for_locking(monkeypatch):
    async with open_session() as s:
        _, _, main, reseller, _ = await _world(s)
        own = await _coupon(s, owner_key=str(reseller.id), store_id=reseller.id)
        await _coupon(s, owner_key="admin", store_id=None, scope="domain")
        other_store = await _coupon(s, owner_key=str(main.id), store_id=main.id)  # same code, another store: invisible here
        await s.commit()
        assert (await catalog.find_coupon(s, reseller, "save", lock=False)).id == own.id
        assert (await catalog.find_coupon(s, reseller, "save", lock=True)).id == own.id
        assert (await catalog.find_coupon(s, main, "save", lock=True)).id == other_store.id
        assert await catalog.find_coupon(s, reseller, "nope", lock=True) is None


def test_source_guard_the_locking_statement_names_one_coupon():
    import inspect

    src = inspect.getsource(catalog.find_coupon)
    assert "Coupon.id == rows[0].id" in src and "with_for_update" in src
    assert src.index("with_for_update") > src.index("rows.sort")  # the lock comes after the winner is chosen, never on the broad query


def test_runner_secrets_are_wired_end_to_end():
    """Core knows the per-runner secrets, the installer generates them, each runner reads its own (shared one is the fallback)."""
    from pathlib import Path

    root = Path(__file__).parents[3]
    assert "MELORIN_MAIN_BOT_SECRET" in (root / "scripts/install_server.sh").read_text()
    assert "MELORIN_RESELLER_BOT_SECRET" in (root / "scripts/install_server.sh").read_text()
    env = (root / ".env.example").read_text()
    assert "MELORIN_MAIN_BOT_SECRET=" in env and "MELORIN_RESELLER_BOT_SECRET=" in env
    main, reseller = (
        (root / "apps/telegram-main/runner.py").read_text(),
        "".join(f.read_text() for f in sorted((root / "apps/telegram-reseller").rglob("*.py"))),
    )
    assert 'secret_env = "MELORIN_MAIN_BOT_SECRET"' in main and "os.environ.get(self.secret_env)" in main
    assert 'secret_env = "MELORIN_RESELLER_BOT_SECRET"' in reseller and 'os.environ.get("MELORIN_RESELLER_BOT_SECRET")' in reseller


async def test_per_customer_limit_counts_each_store_separately_even_for_a_platform_coupon():
    from melorin.kernel.models.catalog import CouponRedemption

    async with open_session() as s:
        referrer, customer, main, reseller, product = await _world(s)
        platform = await _coupon(s, owner_key="admin", store_id=None, scope="domain")
        o1 = await make_order(s, user=customer, store=main, product=product)
        o2 = await make_order(s, user=customer, store=reseller, product=product)
        s.add(CouponRedemption(coupon_id=platform.id, order_id=o1.id, user_id=customer.id, store_id=main.id, amount=100, currency="IRT"))
        await s.commit()
        assert await catalog.customer_redemptions(s, platform.id, customer.id, main.id) == 1  # used in main ...
        assert (
            await catalog.customer_redemptions(s, platform.id, customer.id, reseller.id) == 0
        )  # ... still available in the reseller store
        s.add(
            CouponRedemption(coupon_id=platform.id, order_id=o2.id, user_id=customer.id, store_id=reseller.id, amount=100, currency="IRT")
        )
        await s.commit()
        assert await catalog.customer_redemptions(s, platform.id, customer.id, reseller.id) == 1
        assert await catalog.customer_redemptions(s, platform.id, referrer.id, main.id) == 0  # other customers unaffected


def test_compose_runners_get_a_minimal_environment_without_env_file():
    """A bot runner container holds only what it needs: no .env (DB password, JWT/encryption keys, other runner's secret)."""
    import re
    from pathlib import Path

    text = (Path(__file__).parents[3] / "docker-compose.yml").read_text()
    services = text.split("\nvolumes:")[0].split("\nservices:\n")[1]
    blocks = {m.group(1): m.group(0) for m in re.finditer(r"^  (\w+):\n(?:(?:    .*|)\n?)*", services, re.M)}
    assert {"api", "worker", "telegram_main", "telegram_reseller"} <= set(blocks)
    for name, own, other in (
        ("telegram_main", "MELORIN_MAIN_BOT_SECRET", "MELORIN_RESELLER_BOT_SECRET"),
        ("telegram_reseller", "MELORIN_RESELLER_BOT_SECRET", "MELORIN_MAIN_BOT_SECRET"),
    ):
        code = "\n".join(line for line in blocks[name].splitlines() if not line.lstrip().startswith("#"))
        assert "env_file" not in code, f"{name} must not load the whole .env"
        assert own in code and other not in code, f"{name} gets its own secret only"
        assert not any(k in code for k in ("JWT", "ENCRYPTION", "POSTGRES", "DATABASE", "METRICS", "HEALTH_TOKEN")), name
    for name in ("api", "worker"):  # Core itself keeps the full environment
        assert "env_file: [.env]" in blocks[name]


def test_update_generates_both_runner_secrets_and_fails_closed_without_openssl():
    """`melorin.sh update` must create the missing per-runner secrets before `compose up`, and never write an empty one."""
    from pathlib import Path

    sh = (Path(__file__).parents[3] / "melorin.sh").read_text()
    update = sh.split("do_update() {")[1].split("\n}\n")[0]
    assert "MELORIN_MAIN_BOT_SECRET" in update and "MELORIN_RESELLER_BOT_SECRET" in update
    assert update.index("MELORIN_MAIN_BOT_SECRET") < update.index("compose up -d")
    assert "-ge 32" in update  # an empty/short value (openssl missing) aborts instead of being stored
