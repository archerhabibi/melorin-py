"""Admin «بررسی هویت»: enriched list, optional note on dismiss, reopen, and the screen/route wiring."""

from pathlib import Path

from _source import _raw_text, read_web_source

import pytest

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import db
from melorin.core.errors import AppError
from melorin.modules.admin import router as admin
from melorin.kernel.models.identity import Identity, IdentityLinkReview, User
from melorin.kernel.models.orders import Order
from melorin.kernel.models.system import AuditEvent

PROJECT = Path(__file__).resolve().parents[3]
TABLES = [User.__table__, Identity.__table__, IdentityLinkReview.__table__, Order.__table__, AuditEvent.__table__]


@pytest.fixture
async def session(tmp_path):
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/r.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c, tables=TABLES))
    async with db.session_factory()() as s:
        yield s
    await db.engine().dispose()


async def seed(s):
    a, b = User(display_name="Ali", email="ali@x.io"), User(display_name="Guest", is_guest=True)
    s.add_all([a, b])
    await s.flush()
    s.add(Identity(user_id=a.id, provider="email", subject="ali@x.io"))
    r = IdentityLinkReview(
        email="ali@x.io", source_user_id=b.id, candidate_user_ids=[str(a.id)], provider="google", reason="verified_email_matches_other_user"
    )
    s.add(r)
    await s.commit()
    return a, b, r


async def test_list_carries_both_sides_and_filters_by_status(session):
    a, b, r = await seed(session)
    rows = await admin.identity_link_reviews(None, session)
    assert len(rows) == 1 and rows[0]["source_user"]["display_name"] == "Guest" and rows[0]["source_user"]["is_guest"] is True
    assert rows[0]["candidates"][0]["email"] == "ali@x.io" and rows[0]["candidates"][0]["providers"] == ["email"]
    assert rows[0]["candidates"][0]["orders"] == 0 and rows[0]["resolved_at"] is None
    assert await admin.identity_link_reviews(None, session, status="dismissed") == []
    assert len(await admin.identity_link_reviews(None, session, status="all")) == 1
    with pytest.raises(AppError):
        await admin.identity_link_reviews(None, session, status="bogus")


async def test_dismiss_with_note_then_reopen(session):
    a, b, r = await seed(session)
    admin_user = User(display_name="adm")
    session.add(admin_user)
    await session.commit()
    await admin.dismiss_identity_review(r.id, admin_user, session, admin.ReviewNoteIn(note="  دو نفر متفاوت  "))
    row = (await admin.identity_link_reviews(None, session, status="dismissed"))[0]
    assert (
        row["status"] == "dismissed"
        and row["resolution_note"] == "دو نفر متفاوت"
        and row["resolved_by"] == admin_user.id
        and row["resolved_at"]
    )
    with pytest.raises(AppError):  # already closed
        await admin.dismiss_identity_review(r.id, admin_user, session, None)
    await admin.reopen_identity_review(r.id, admin_user, session)
    row = (await admin.identity_link_reviews(None, session))[0]
    assert row["status"] == "open" and row["resolution_note"] is None and row["resolved_by"] is None
    with pytest.raises(AppError):  # only dismissed items can be reopened
        await admin.reopen_identity_review(r.id, admin_user, session)


async def test_dismiss_without_body_still_works_for_old_clients(session):
    a, b, r = await seed(session)
    admin_user = User(display_name="adm")
    session.add(admin_user)
    await session.commit()
    assert await admin.dismiss_identity_review(r.id, admin_user, session) == {"ok": True}


def test_screen_is_wired_into_the_admin_panel_and_bot_keeps_its_contract():
    extra = read_web_source(PROJECT / "apps/admin-web/src/AdminExtra.jsx")
    assert '"بررسی هویت": IdentityReviewsView' in extra and "function Reviews(" not in extra
    view = read_web_source(PROJECT / "apps/admin-web/src/IdentityReviewsView.jsx")
    assert "identity-link-reviews?status=all" in view and "reopen" in view and "dismiss" in view
    bot = _raw_text(PROJECT / "apps/telegram-main/runner.py")
    assert 'f"wla:{sid}:{c}"' in bot and 'f"wld:{sid}"' in bot  # callback data format is part of the Core contract
