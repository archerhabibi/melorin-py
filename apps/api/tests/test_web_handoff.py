"""Bot account button: Core issues a single-use token that signs the Telegram user into the store website."""

import types

import pytest
from fastapi import Response

import melorin.models  # noqa: F401
from melorin.core import db
from melorin.core.errors import AppError
from melorin.modules.identity import router, service
from melorin.modules.identity.models import Identity, RefreshToken, User, VerificationCode
from melorin.modules.identity.schemas import WebHandoffIn, WebHandoffRedeem
from melorin.modules.stores.models import Store
from melorin.modules.system.models import AuditEvent, SecurityEvent

TABLES = [
    User.__table__,
    Identity.__table__,
    RefreshToken.__table__,
    VerificationCode.__table__,
    Store.__table__,
    AuditEvent.__table__,
    SecurityEvent.__table__,
]
REQ = types.SimpleNamespace(headers={"user-agent": "pytest"}, cookies={})


@pytest.fixture
async def s(tmp_path):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/h.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=TABLES))
    async with db.session_factory()() as session:
        yield session
    await db.engine().dispose()


async def _user(s, sub="42", **kw):
    u = User(display_name="TG", **kw)
    s.add(u)
    await s.flush()
    s.add(Identity(user_id=u.id, provider="telegram", subject=sub, data={}))
    await s.commit()
    return u


async def test_handoff_url_comes_from_core_and_token_signs_in_once(s):
    u = await _user(s)
    out = await router.create_web_handoff(WebHandoffIn(), u, s)
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
    out = await router.create_web_handoff(WebHandoffIn(store_id=st.id), u, s)
    assert out.url.startswith("https://shop.example.ir/#/auth/handoff?t=")


async def test_expired_or_unknown_token_and_admins_are_refused(s):
    u = await _user(s)
    token = await service.create_web_handoff(s, u)
    vc = await s.scalar(__import__("sqlalchemy").select(VerificationCode))
    vc.expires_at = vc.expires_at.replace(year=2000)
    await s.commit()
    for t in (token, "x" * 40):
        with pytest.raises(AppError) as e:
            await router.web_handoff_redeem(WebHandoffRedeem(token=t), s, REQ, Response())
        assert e.value.code == "HANDOFF_INVALID"
    admin = await _user(s, sub="43", is_super_admin=True)
    with pytest.raises(AppError) as e:
        await router.create_web_handoff(WebHandoffIn(), admin, s)
    assert e.value.status == 403
