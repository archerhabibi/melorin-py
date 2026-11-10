"""Bot account button: Core issues a single-use token that signs the Telegram user into the store website."""

import pytest
from fastapi import Response

from _chan import auth_for, fake_request

import melorin.models  # noqa: F401
from melorin.core import db
from melorin.core.errors import AppError
from melorin.modules.identity import router, service
from melorin.kernel.models.identity import Identity, RefreshToken, User, VerificationCode
from melorin.modules.identity.schemas import WebHandoffIn, WebHandoffRedeem
from melorin.kernel.models.stores import Store
from melorin.kernel.models.system import AuditEvent, SecurityEvent

TABLES = [
    User.__table__,
    Identity.__table__,
    RefreshToken.__table__,
    VerificationCode.__table__,
    Store.__table__,
    AuditEvent.__table__,
    SecurityEvent.__table__,
]
REQ = fake_request("localhost")  # development: an unknown host falls back to the main store


@pytest.fixture
async def s(tmp_path):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/h.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c))
    async with db.session_factory()() as session:
        yield session
    await db.engine().dispose()


async def _main(s):
    from sqlalchemy import select

    st = await s.scalar(select(Store).where(Store.kind == "main"))
    if st is None:
        st = Store(kind="main", name="Main", slug="main")
        s.add(st)
        await s.commit()
    return st


async def _user(s, sub="42", **kw):
    u = User(display_name="TG", **kw)
    s.add(u)
    await s.flush()
    s.add(Identity(user_id=u.id, provider="telegram", subject=sub, data={}))
    await s.commit()
    return u


async def test_handoff_url_comes_from_core_and_token_signs_in_once(s):
    u = await _user(s)
    main = await _main(s)
    out = await router.create_web_handoff(WebHandoffIn(), auth_for(u, main, "bot"), s)
    assert out.url.startswith("http://localhost:3000/#/auth/handoff?t=") and out.google_linked is False
    token = out.url.split("?t=")[1]
    resp = Response()
    pair = await router.web_handoff_redeem(WebHandoffRedeem(token=token), s, REQ, resp)
    assert pair.user_id == u.id and "melorin_refresh" in resp.headers.get("set-cookie", "")
    with pytest.raises(AppError) as e:  # single use
        await router.web_handoff_redeem(WebHandoffRedeem(token=token), s, REQ, Response())
    assert e.value.code == "HANDOFF_INVALID"


async def test_reseller_store_uses_its_own_domain(s):
    u = await _user(s)
    st = Store(kind="reseller", name="R", slug="r", domain="shop.example.ir")
    s.add(st)
    await s.commit()
    out = await router.create_web_handoff(WebHandoffIn(store_id=st.id), auth_for(u, st, "bot"), s)
    assert out.url.startswith("https://shop.example.ir/#/auth/handoff?t=")


async def test_expired_or_unknown_token_and_admins_are_refused(s):
    u = await _user(s)
    main = await _main(s)
    token = await service.create_web_handoff(s, u, main.id)
    vc = await s.scalar(__import__("sqlalchemy").select(VerificationCode))
    vc.expires_at = vc.expires_at.replace(year=2000)
    await s.commit()
    for t in (token, "x" * 40):
        with pytest.raises(AppError) as e:
            await router.web_handoff_redeem(WebHandoffRedeem(token=t), s, REQ, Response())
        assert e.value.code == "HANDOFF_INVALID"
    admin = await _user(s, sub="43", is_super_admin=True)
    with pytest.raises(AppError) as e:
        await router.create_web_handoff(WebHandoffIn(), auth_for(admin, main, "bot"), s)
    assert e.value.status == 403


async def test_handoff_only_works_on_the_store_it_was_minted_for(s):
    """The token a reseller's bot hands out signs in on THAT reseller's site, never on the main store's (or another's)."""
    u = await _user(s)
    main = await _main(s)
    a = Store(kind="reseller", name="A", slug="a", domain="a.example.ir")
    s.add(a)
    await s.commit()
    token = (await router.create_web_handoff(WebHandoffIn(), auth_for(u, a, "bot"), s)).url.split("?t=")[1]
    with pytest.raises(AppError) as e:  # redeemed on the main store's site
        await router.web_handoff_redeem(WebHandoffRedeem(token=token), s, REQ, Response())
    assert e.value.code == "HANDOFF_INVALID"
    with pytest.raises(AppError) as e:  # and a mismatched client hint on the right host is refused too
        await router.create_web_handoff(WebHandoffIn(store_id=main.id), auth_for(u, a, "bot"), s)
    assert e.value.code == "CHANNEL_MISMATCH"
    token = (await router.create_web_handoff(WebHandoffIn(), auth_for(u, a, "bot"), s)).url.split("?t=")[1]
    resp = Response()
    pair = await router.web_handoff_redeem(WebHandoffRedeem(token=token), s, fake_request("a.example.ir"), resp)
    assert pair.store_id == a.id and pair.channel == "site"
