"""Admin «بررسی هویت»: enriched list, optional note on dismiss, reopen, and the screen/route wiring."""

from pathlib import Path

from _source import _raw_text, read_web_source

import pytest

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.kernel.models.person import Person
from melorin.core import db
from melorin.core.errors import AppError
from melorin.modules.admin import identity_reviews as admin_identity_reviews
from melorin.kernel.models.identity import Identity, IdentityLinkReview, User
from melorin.kernel.models.orders import Order
from melorin.kernel.models.system import AuditEvent

PROJECT = Path(__file__).resolve().parents[4]
TABLES = [Person.__table__, User.__table__, Identity.__table__, IdentityLinkReview.__table__, Order.__table__, AuditEvent.__table__]


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
    rows = await admin_identity_reviews.identity_link_reviews(None, session)
    assert len(rows) == 1 and rows[0]["source_user"]["display_name"] == "Guest" and rows[0]["source_user"]["is_guest"] is True
    assert rows[0]["candidates"][0]["email"] == "ali@x.io" and rows[0]["candidates"][0]["providers"] == ["email"]
    assert rows[0]["candidates"][0]["orders"] == 0 and rows[0]["resolved_at"] is None
    assert await admin_identity_reviews.identity_link_reviews(None, session, status="dismissed") == []
    assert len(await admin_identity_reviews.identity_link_reviews(None, session, status="all")) == 1
    with pytest.raises(AppError):
        await admin_identity_reviews.identity_link_reviews(None, session, status="bogus")


async def test_rows_settled_by_core_are_flagged_auto_so_the_panel_keeps_them_out_of_the_manual_queue(session):
    a, b, r = await seed(session)
    assert (await admin_identity_reviews.identity_link_reviews(None, session))[0]["auto"] is False
    r.status, r.resolution_note = "linked", "auto:shell_into_other"
    await session.commit()
    (row,) = await admin_identity_reviews.identity_link_reviews(None, session, status="linked")
    assert row["auto"] is True
    r.resolution_note = "merged by hand"  # an admin's own link is NOT automatic
    await session.commit()
    assert (await admin_identity_reviews.identity_link_reviews(None, session, status="linked"))[0]["auto"] is False


async def test_dismiss_with_note_then_reopen(session):
    a, b, r = await seed(session)
    admin_user = User(display_name="adm")
    session.add(admin_user)
    await session.commit()
    await admin_identity_reviews.dismiss_identity_review(
        r.id, admin_user, session, admin_identity_reviews.ReviewNoteIn(note="  دو نفر متفاوت  ")
    )
    row = (await admin_identity_reviews.identity_link_reviews(None, session, status="dismissed"))[0]
    assert (
        row["status"] == "dismissed"
        and row["resolution_note"] == "دو نفر متفاوت"
        and row["resolved_by"] == admin_user.id
        and row["resolved_at"]
    )
    with pytest.raises(AppError):  # already closed
        await admin_identity_reviews.dismiss_identity_review(r.id, admin_user, session, None)
    await admin_identity_reviews.reopen_identity_review(r.id, admin_user, session)
    row = (await admin_identity_reviews.identity_link_reviews(None, session))[0]
    assert row["status"] == "open" and row["resolution_note"] is None and row["resolved_by"] is None
    with pytest.raises(AppError):  # only dismissed items can be reopened
        await admin_identity_reviews.reopen_identity_review(r.id, admin_user, session)


async def test_dismiss_without_body_still_works_for_old_clients(session):
    a, b, r = await seed(session)
    admin_user = User(display_name="adm")
    session.add(admin_user)
    await session.commit()
    assert await admin_identity_reviews.dismiss_identity_review(r.id, admin_user, session) == {"ok": True}


def test_screen_is_wired_into_the_admin_panel_and_bot_keeps_its_contract():
    extra = read_web_source(PROJECT / "apps/admin-web/src/app/AdminExtra.tsx")
    assert "IdentityHubView" in extra and "function Reviews(" not in extra  # one «هویت» screen: review queue + auto report + devices
    hub = read_web_source(PROJECT / "apps/admin-web/src/features/identity/IdentityHubView.tsx")
    assert "IdentityReviewsView" in hub and 'section="merges"' in hub and 'section="devices"' in hub
    view = read_web_source(PROJECT / "apps/admin-web/src/features/identity/IdentityReviewsView.tsx")
    drawer = read_web_source(PROJECT / "apps/admin-web/src/features/identity/IdentityReviewDrawer.tsx")  # actions live in the drawer after the split
    assert "identity-link-reviews?status=all" in view and "reopen" in drawer and "dismiss" in view
    bot = _raw_text(PROJECT / "apps/telegram-main/runner.py")
    assert 'f"wla:{sid}:{c}"' in bot and 'f"wld:{sid}"' in bot  # callback data format is part of the Core contract
