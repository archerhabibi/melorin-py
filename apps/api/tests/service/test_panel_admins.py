"""One PasarGuard Operator admin per store and panel: adapter calls, planning/sync, provisioning owner, profile change requests."""

import datetime as dt
import json
import uuid
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import select

from _db import make_store, make_user, open_session
from melorin.kernel.models.vpn import Panel, PanelAdmin, PanelAdminChangeRequest
from melorin.modules.panelops import panel_admins as svc
from melorin.modules.panel_integrations.adapters import pasarguard
from melorin.modules.panel_integrations.adapters.base import AccountSpec, ErrorKind, PanelError
from melorin.modules.panel_integrations.adapters.pasarguard import PasarGuardAdapter

GB = 1024**3


@pytest.fixture(autouse=True)
def _clear_tokens():
    pasarguard._TOKENS.clear()
    yield
    pasarguard._TOKENS.clear()


class Fake:
    """PasarGuard with users, admins and roles (Owner id 1, Operator id 3)."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.admins: dict[str, dict] = {"owner": {"id": 1, "username": "owner"}}
        self.calls: list[tuple[str, str, dict]] = []
        self.next_uid, self.next_aid = 1, 2
        self.fail_set_owner = False

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path, method = req.url.path, req.method
        body = json.loads(req.content) if req.content and req.headers.get("content-type", "").startswith("application/json") else {}
        q = {k: v[0] for k, v in parse_qs(req.url.query.decode()).items()}
        self.calls.append((method, path, body or q))
        if path == "/api/admin/token":
            return httpx.Response(200, json={"access_token": "t"})
        if path == "/api/admin-roles/simple":
            return httpx.Response(
                200,
                json={
                    "roles": [
                        {"id": 1, "name": "owner", "is_owner": True},
                        {"id": 3, "name": "operator", "is_owner": False},
                        {"id": 7, "name": "melorin-store", "is_owner": False},
                    ]
                },
            )
        if path == "/api/admins":
            return httpx.Response(200, json={"admins": [a for a in self.admins.values() if a["username"] == q.get("username")]})
        if path == "/api/admin" and method == "POST":
            if body["username"] in self.admins:
                return httpx.Response(409, json={"detail": "Admin already exists"})
            a = {"id": self.next_aid, "username": body["username"], **body}
            self.next_aid += 1
            self.admins[a["username"]] = a
            return httpx.Response(201, json=a)
        if path.startswith("/api/admin/by-id/") and method == "PUT":
            aid = int(path.rsplit("/", 1)[1])
            a = next(x for x in self.admins.values() if x["id"] == aid)
            a.update(body)
            return httpx.Response(200, json=a)
        if path == "/api/user" and method == "POST":
            u = {"id": self.next_uid, "used_traffic": 0, "admin": {"id": 1, "username": "owner"}, **body}
            self.next_uid += 1
            self.users[u["username"]] = u
            return httpx.Response(200, json=u)
        if path.startswith("/api/user/by-username/"):
            u = self.users.get(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=u) if u else httpx.Response(404, json={"detail": "nf"})
        if path.startswith("/api/user/by-id/") and path.endswith("/set_owner"):
            if self.fail_set_owner:
                return httpx.Response(500, json={"detail": "boom"})
            uid = int(path.split("/")[4])
            u = next(x for x in self.users.values() if x["id"] == uid)
            u["admin"] = {"id": self.admins[q["admin_username"]]["id"], "username": q["admin_username"]}
            return httpx.Response(200, json=u)
        if path == "/api/users/bulk/set_owner":
            return httpx.Response(200, json={"count": len(body["ids"])})
        return httpx.Response(404, json={"detail": "no route"})


def adapter(fake: Fake, **cfg) -> PasarGuardAdapter:
    return PasarGuardAdapter(
        "https://p.example.com", {"username": "owner", "password": "x"}, {"group_ids": [1], **cfg}, transport=httpx.MockTransport(fake)
    )


def spec(owner=None):
    return AccountSpec("acc_1", dt.datetime(2030, 1, 1, tzinfo=dt.UTC), 5 * GB, 2, "n", owner=owner)


# ------------------------------------------------------------------ adapter
async def test_new_account_is_owned_by_the_store_admin():
    fake = Fake()
    a = adapter(fake)
    await a.ensure_admin("rs_ab12", "Passw0rd!Passw0rd!")
    acc = await a.create_account(spec(owner="rs_ab12"))
    assert fake.users["acc_1"]["admin"]["username"] == "rs_ab12" and acc.username == "acc_1"
    assert fake.admins["rs_ab12"]["role_id"] == 3  # Operator, never the owner role


async def test_create_without_owner_keeps_old_behaviour_and_retry_is_idempotent():
    fake = Fake()
    a = adapter(fake)
    await a.create_account(spec())
    assert not any(c[1].endswith("/set_owner") for c in fake.calls)
    await a.ensure_admin("rs_x", "Passw0rd!Passw0rd!")
    await a.create_account(spec(owner="rs_x"))  # existing user (retry) is moved, not duplicated
    await a.create_account(spec(owner="rs_x"))
    assert len(fake.users) == 1 and sum(c[1].endswith("/set_owner") for c in fake.calls) == 1


async def test_set_owner_failure_is_transient_so_the_order_retries():
    fake = Fake()
    a = adapter(fake)
    await a.ensure_admin("rs_x", "Passw0rd!Passw0rd!")
    fake.fail_set_owner = True
    with pytest.raises(PanelError) as e:
        await a.create_account(spec(owner="rs_x"))
    assert e.value.kind == ErrorKind.TRANSIENT


async def test_ensure_admin_is_idempotent_and_adopts_an_existing_one():
    fake = Fake()
    a = adapter(fake)
    first = await a.ensure_admin("rs_x", "Passw0rd!Passw0rd!", profile={"profile_title": "Shop", "telegram_id": 5})
    again = await a.ensure_admin("rs_x", "Passw0rd!Passw0rd!")
    assert first["id"] == again["id"] and len([x for x in fake.admins if x == "rs_x"]) == 1
    created = next(c for c in fake.calls if c[0] == "POST" and c[1] == "/api/admin")[2]
    assert created["profile_title"] == "Shop" and created["telegram_id"] == 5 and created["role_id"] == 3


async def test_ensure_admin_moves_an_existing_admin_to_the_wanted_role_but_never_an_owner():
    fake = Fake()
    a = adapter(fake)
    await a.ensure_admin("rs_x", "Passw0rd!Passw0rd!")  # created as operator (3)
    assert fake.admins["rs_x"]["role_id"] == 3
    await a.ensure_admin("rs_x", "Passw0rd!Passw0rd!", role="melorin-store")
    assert fake.admins["rs_x"]["role_id"] == 7
    seen = len(fake.calls)
    await a.ensure_admin("rs_x", "Passw0rd!Passw0rd!", role="melorin-store")  # already there: the role is not sent again
    put = next(c for c in fake.calls[seen:] if c[0] == "PUT")
    assert "role_id" not in put[2]
    fake.admins["boss"] = {"id": 9, "username": "boss", "role": {"id": 1, "name": "owner", "is_owner": True}}
    await a.ensure_admin("boss", "Passw0rd!Passw0rd!", role="melorin-store")
    assert "role_id" not in fake.admins["boss"]  # an owner keeps the owner role
    # the real panel answers with a `role` object: compare by its id
    fake.admins["real"] = {"id": 11, "username": "real", "role": {"id": 7, "name": "melorin-store", "is_owner": False}}
    seen = len(fake.calls)
    await a.ensure_admin("real", "Passw0rd!Passw0rd!", role="melorin-store")
    assert "role_id" not in next(c for c in fake.calls[seen:] if c[0] == "PUT")[2]


async def test_missing_operator_role_is_permanent():
    fake = Fake()
    with pytest.raises(PanelError) as e:
        await adapter(fake).ensure_admin("rs_x", "Passw0rd!Passw0rd!", role="nonexistent")
    assert e.value.kind == ErrorKind.PERMANENT


# ------------------------------------------------------------------ naming / passwords / validation
def test_usernames_and_passwords_fit_the_panel_rules():
    class S:
        def __init__(self, kind, slug, id_="0" * 32):
            self.kind, self.slug = kind, slug
            self.id = type("U", (), {"hex": id_})()

    assert svc.admin_username(S("main", "main")) == "ml_main"
    assert svc.admin_username(S("reseller", "reseller-ab12cd34")) == "rs_ab12cd34"
    assert len(svc.admin_username(S("reseller", "reseller-" + "x" * 80))) <= 34
    for _ in range(30):
        p = svc.generate_password()
        assert len(p) >= 12 and sum(c.isdigit() for c in p) >= 2 and sum(c.isupper() for c in p) >= 2 and sum(c.islower() for c in p) >= 2


def test_profile_validation():
    ok = svc.clean_profile({"profile_title": " My VPN ", "support_url": "https://t.me/x", "telegram_id": "123", "note": None})
    assert ok == {"profile_title": "My VPN", "support_url": "https://t.me/x", "telegram_id": 123}
    for bad in (
        {"support_url": "javascript:alert(1)"},
        {"profile_title": "<b>x</b>"},
        {"telegram_id": -1},
        {"discord_webhook": "https://evil.example/hook"},
        {"unknown": "x"},
    ):
        with pytest.raises(svc.ProfileError):
            svc.clean_profile(bad)
    with pytest.raises(svc.ProfileError):  # a reseller may not ask for sub_domain / note
        svc.clean_profile({"sub_domain": "https://x.example"}, allowed=svc.REQUESTABLE_FIELDS)
    assert svc.clean_profile({"profile_title": ""}) == {"profile_title": ""}  # empty clears


# ------------------------------------------------------------------ planning / sync / provisioning owner
class FakeAdapter:
    def __init__(self, fail=False):
        self.admins, self.profiles, self.ensured, self.owned, self.fail, self.closed = {}, [], [], [], fail, 0

    async def ensure_admin(self, username, password, *, role="operator", profile=None):
        if self.fail:
            raise PanelError(ErrorKind.TRANSIENT, "panel down")
        self.admins[username] = password
        self.ensured.append((username, profile))
        return {"id": len(self.admins) + 1, "username": username}

    async def update_admin_profile(self, remote_id, profile, *, password=None):
        if self.fail:
            raise PanelError(ErrorKind.TRANSIENT, "panel down")
        self.profiles.append((remote_id, profile))
        return {}

    async def bulk_set_owner(self, refs, owner):
        self.owned.append((sorted(refs), owner))
        return len(refs)

    async def close(self):
        self.closed += 1


@pytest.fixture
def fake_adapter(monkeypatch):
    holder = {"a": FakeAdapter()}
    monkeypatch.setattr("melorin.modules.panel_integrations.adapters.registry.build_adapter", lambda panel, server=None: holder["a"])
    return holder


async def _world(s):
    main = await make_store(s, kind="main")
    owner = await make_user(s)
    r1 = await make_store(s, kind="reseller", slug="reseller-aaaa1111", owner=owner)
    panel = Panel(name="P", kind="pasarguard", base_url="https://p.example.com", is_enabled=True, config={"group_ids": [1]})
    s.add(panel)
    await s.flush()
    return main, r1, panel


async def test_every_store_gets_its_own_admin_and_a_later_reseller_gets_one_too(fake_adapter):
    async with open_session() as s:
        main, r1, panel = await _world(s)
        res = await svc.sync_all(s)
        assert res == {"planned": 2, "synced": 2, "failed": 0}
        rows = {r.store_id: r for r in (await s.scalars(select(PanelAdmin))).all()}
        assert rows[main.id].username == "ml_main" and rows[r1.id].username == "rs_aaaa1111"
        assert all(r.status == "active" and r.remote_id for r in rows.values())
        assert set(fake_adapter["a"].admins) == {"ml_main", "rs_aaaa1111"}
        await make_store(s, kind="reseller", slug="reseller-bbbb2222")
        res = await svc.sync_all(s)
        assert res["planned"] == 1 and res["synced"] == 1 and "rs_bbbb2222" in fake_adapter["a"].admins
        assert (await svc.sync_all(s))["planned"] == 0  # nothing left to do


async def test_unmanaged_and_non_pasarguard_panels_are_skipped(fake_adapter):
    async with open_session() as s:
        main, r1, panel = await _world(s)
        panel.config = {"group_ids": [1], "admin_per_store": False}
        s.add(Panel(name="M", kind="mock", base_url="https://m.example.com", is_enabled=True))
        await s.flush()
        assert (await svc.sync_all(s))["planned"] == 0
        assert (await s.scalars(select(PanelAdmin))).all() == []


async def test_failed_sync_is_recorded_and_retried(fake_adapter):
    async with open_session() as s:
        await _world(s)
        fake_adapter["a"].fail = True
        res = await svc.sync_all(s)
        assert res["failed"] == 2
        row = (await s.scalars(select(PanelAdmin))).first()
        assert row.status == "error" and "panel down" in row.last_error
        fake_adapter["a"].fail = False
        assert (await svc.sync_all(s))["synced"] == 2


async def test_existing_accounts_are_adopted_once(fake_adapter):
    from _db import make_order, make_product
    from melorin.kernel.models.vpn import VpnAccount

    async with open_session() as s:
        main, r1, panel = await _world(s)
        user, product = await make_user(s), await make_product(s, price=1)
        order = await make_order(s, user=user, store=r1, product=product, total=1, status="paid", number="N1")
        s.add(
            VpnAccount(
                username="old_1",
                user_id=user.id,
                store_id=r1.id,
                order_id=order.id,
                product_id=product.id,
                panel_id=panel.id,
                panel_ref="17",
                status="active",
            )
        )
        await s.flush()
        await svc.sync_all(s)
        assert fake_adapter["a"].owned == [(["17"], "rs_aaaa1111")]
        await svc.sync_all(s)
        assert len(fake_adapter["a"].owned) == 1  # adopted_at set: never repeated


async def test_owner_for_creates_the_admin_lazily_and_fails_transient_when_not_ready(fake_adapter):
    async with open_session() as s:
        main, r1, panel = await _world(s)
        a = fake_adapter["a"]
        assert await svc.owner_for(s, panel, r1.id, a) == "rs_aaaa1111"
        assert await svc.owner_for(s, panel, main.id, a) == "ml_main"
        r2 = await make_store(s, kind="reseller", slug="reseller-cccc3333")
        a.fail = True
        with pytest.raises(PanelError) as e:
            await svc.owner_for(s, panel, r2.id, a)
        assert e.value.kind == ErrorKind.TRANSIENT
        assert await svc.owner_for(s, panel, None, a) is None
        panel.config = {"admin_per_store": False}
        assert await svc.owner_for(s, panel, r1.id, a) is None


async def test_provisioning_passes_the_store_admin_as_owner(monkeypatch):
    """The real provision path: the AccountSpec carries the admin of the order's store."""
    from melorin.modules.orders import provisioning as vpn
    from test_provisioning_db import ScriptedPanel
    from test_provisioning_db import _world as prov_world

    async with open_session() as s:
        w = await prov_world(s)
        seen = {}

        async def fake_owner(session, panel, store_id, adapter):
            seen["store_id"] = store_id
            return "rs_test"

        monkeypatch.setattr(svc, "owner_for", fake_owner)
        panel = ScriptedPanel()
        monkeypatch.setattr(vpn, "build_adapter", lambda _p, _s=None: panel)
        await vpn.provision_order(s, w["order"].id)
        assert panel.created and panel.created[0].owner == "rs_test" and seen["store_id"] == w["order"].store_id


# ------------------------------------------------------------------ admin edits / reseller requests
async def test_admin_edits_profile_and_it_reaches_the_panel(fake_adapter):
    async with open_session() as s:
        main, r1, panel = await _world(s)
        await svc.sync_all(s)
        res = await svc.apply_profile(s, r1.id, {"profile_title": "Shop", "support_url": "https://t.me/shop"})
        assert res[0]["synced"] and res[0]["error"] is None
        assert fake_adapter["a"].profiles[-1][1] == {"profile_title": "Shop", "support_url": "https://t.me/shop"}
        row = await s.scalar(select(PanelAdmin).where(PanelAdmin.store_id == r1.id))
        assert row.profile["profile_title"] == "Shop" and row.profile_synced
        other = await s.scalar(select(PanelAdmin).where(PanelAdmin.store_id == main.id))
        assert not other.profile  # profile is per store: the main store admin is untouched


async def test_profile_push_failure_is_kept_and_retried_by_the_worker(fake_adapter):
    async with open_session() as s:
        main, r1, panel = await _world(s)
        await svc.sync_all(s)
        fake_adapter["a"].fail = True
        res = await svc.apply_profile(s, r1.id, {"profile_title": "Shop"})
        assert res[0]["synced"] is False and "panel down" in res[0]["error"]
        fake_adapter["a"].fail = False
        await svc.sync_all(s)
        row = await s.scalar(select(PanelAdmin).where(PanelAdmin.store_id == r1.id))
        assert row.profile_synced and fake_adapter["a"].ensured[-1] == ("rs_aaaa1111", {"profile_title": "Shop"})


async def test_password_is_encrypted_and_never_in_public_row(fake_adapter):
    async with open_session() as s:
        main, r1, panel = await _world(s)
        await svc.sync_all(s)
        row = await s.scalar(select(PanelAdmin).where(PanelAdmin.store_id == r1.id))
        from melorin.core.crypto import decrypt

        pw = decrypt(row.password_enc)
        assert pw == fake_adapter["a"].admins[row.username] and pw not in row.password_enc
        assert "password" not in svc.public_row(row)


async def test_reseller_request_flow_one_pending_then_admin_applies_or_rejects(fake_adapter):
    from melorin.core.errors import AppError
    from melorin.modules.admin import panel_admins as admin_api
    from melorin.modules.reseller.routes import panel_profile as reseller_api

    async with open_session() as s:
        main, r1, panel = await _world(s)
        await svc.sync_all(s)
        user = await make_user(s, super_admin=True)
        ctx = type("Ctx", (), {"store": r1, "user": user})()
        out = await reseller_api.request_change(
            reseller_api.ProfileChangeIn(changes={"profile_title": "New", "support_url": "https://t.me/n"}), ctx, s
        )
        with pytest.raises(AppError) as e:  # second request while one is pending
            await reseller_api.request_change(reseller_api.ProfileChangeIn(changes={"profile_title": "X"}), ctx, s)
        assert e.value.code == "REQUEST_PENDING"
        for bad in ({"sub_domain": "https://x.example"}, {}, {"support_url": "javascript:1"}):
            with pytest.raises(AppError):
                await reseller_api.request_change(reseller_api.ProfileChangeIn(changes=bad), ctx, s)
        assert fake_adapter["a"].profiles == []  # nothing reaches the panel until the admin acts
        res = await admin_api.apply_request(out["id"], admin_api.ReviewIn(changes={"profile_title": "Edited by admin"}, note="ok"), user, s)
        assert res["ok"] and fake_adapter["a"].profiles[-1][1] == {"profile_title": "Edited by admin"}
        r = await s.get(PanelAdminChangeRequest, out["id"])
        assert r.status == "applied" and r.reviewed_by == user.id
        with pytest.raises(AppError) as e:
            await admin_api.apply_request(out["id"], admin_api.ReviewIn(), user, s)
        assert e.value.code == "REQUEST_ALREADY_REVIEWED"
        again = await reseller_api.request_change(reseller_api.ProfileChangeIn(changes={"profile_title": "Z"}), ctx, s)
        await admin_api.reject_request(again["id"], admin_api.ReviewIn(note="no"), user, s)
        assert (await s.get(PanelAdminChangeRequest, again["id"])).status == "rejected"


def test_migration_0040_follows_0039():
    import importlib.util
    from pathlib import Path

    f = Path(__file__).resolve().parents[2] / "alembic/versions/0040_panel_admins.py"
    spec_ = importlib.util.spec_from_file_location("m0040", f)
    m = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(m)
    assert m.down_revision == "0039_target_selection" and len(m.revision) <= 32


# ------------------------------------------------------------------ guards: login clashes, creation races, reset durability
def test_pick_username_never_reuses_a_taken_login_and_stays_within_the_panel_limit():
    class S:
        kind, slug = "reseller", "reseller-" + "x" * 80
        id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    base = svc.admin_username(S)
    assert svc.pick_username(S, set()) == base
    second = svc.pick_username(S, {base})
    assert second != base and len(second) <= 34 and second.endswith("_123456")
    third = svc.pick_username(S, {base, second})
    assert third not in {base, second} and len(third) <= 34 and third.endswith("_1234567812")


async def test_two_stores_whose_slugs_collapse_to_one_name_still_get_separate_panel_admins(fake_adapter):
    """``ab-cd`` and ``ab_cd`` both become ``rs_ab_cd``: the second store must NOT adopt (and re-password) the first one's admin."""
    async with open_session() as s:
        main, r1, panel = await _world(s)
        a = await make_store(s, kind="reseller", slug="reseller-ab-cd")
        b = await make_store(s, kind="reseller", slug="reseller-ab_cd")
        assert (await svc.sync_all(s))["failed"] == 0
        rows = {r.store_id: r for r in (await s.scalars(select(PanelAdmin))).all()}
        names = [rows[st.id].username for st in (main, r1, a, b)]
        assert len(set(names)) == 4 and rows[a.id].username == "rs_ab_cd" and rows[b.id].username.startswith("rs_ab_cd_")
        assert set(fake_adapter["a"].admins) == set(names)  # four logins on the panel, none shared


async def test_the_database_refuses_a_shared_login_and_a_second_pending_request():
    from sqlalchemy.exc import IntegrityError

    async with open_session() as s:
        main, r1, panel = await _world(s)
        s.add(_row(panel, main, "ml_main"))
        await s.flush()
        with pytest.raises(IntegrityError):
            async with s.begin_nested():
                s.add(_row(panel, r1, "ml_main"))
                await s.flush()
        s.add(PanelAdminChangeRequest(store_id=r1.id, changes={"profile_title": "A"}, status="pending"))
        await s.flush()
        with pytest.raises(IntegrityError):
            async with s.begin_nested():
                s.add(PanelAdminChangeRequest(store_id=r1.id, changes={"profile_title": "B"}, status="pending"))
                await s.flush()
        # history is unlimited: only PENDING is unique
        s.add(PanelAdminChangeRequest(store_id=r1.id, changes={"profile_title": "C"}, status="rejected"))
        s.add(PanelAdminChangeRequest(store_id=main.id, changes={"profile_title": "D"}, status="pending"))
        await s.flush()


def _row(panel, store, username):
    return PanelAdmin(panel_id=panel.id, store_id=store.id, username=username, password_enc=svc.encrypt("x"), status="pending")


async def test_losing_the_creation_race_returns_the_winners_row(fake_adapter, monkeypatch):
    """The worker and provisioning both see "no row yet"; the loser's INSERT fails and it must re-read, not crash."""
    async with open_session() as s:
        main, r1, panel = await _world(s)
        winner = _row(panel, r1, "rs_aaaa1111")
        s.add(winner)
        await s.flush()
        real_scalar, calls = s.scalar, {"n": 0}

        async def blind_first_lookup(*a, **kw):
            calls["n"] += 1
            return None if calls["n"] == 1 else await real_scalar(*a, **kw)

        monkeypatch.setattr(s, "scalar", blind_first_lookup)
        row, created = await svc._create_row(s, panel, r1)
        assert created is False and row.id == winner.id
        assert len((await s.scalars(select(PanelAdmin).where(PanelAdmin.store_id == r1.id))).all()) == 1


async def test_reset_password_saves_the_new_secret_before_touching_the_panel(fake_adapter, monkeypatch):
    async with open_session() as s:
        main, r1, panel = await _world(s)
        await svc.sync_all(s)
        row = await s.scalar(select(PanelAdmin).where(PanelAdmin.store_id == r1.id))
        old = svc.decrypt(row.password_enc)
        commits, seen = {"n": 0}, {}
        real_commit = s.commit

        async def counting_commit():
            commits["n"] += 1
            await real_commit()

        async def spy_update(remote_id, profile, *, password=None):
            seen.update(commits=commits["n"], flagged=row.profile_synced is False, stored=svc.decrypt(row.password_enc), pushed=password)
            return {}

        monkeypatch.setattr(s, "commit", counting_commit)
        monkeypatch.setattr(fake_adapter["a"], "update_admin_profile", spy_update)
        new = await svc.reset_password(s, row, panel)
        assert new != old and seen == {"commits": 1, "flagged": True, "stored": new, "pushed": new}
        assert row.profile_synced is True and svc.decrypt(row.password_enc) == new


async def test_reset_password_restores_the_old_secret_when_the_panel_refuses(fake_adapter):
    async with open_session() as s:
        main, r1, panel = await _world(s)
        await svc.sync_all(s)
        row = await s.scalar(select(PanelAdmin).where(PanelAdmin.store_id == r1.id))
        old_enc = row.password_enc
        fake_adapter["a"].fail = True
        with pytest.raises(PanelError):
            await svc.reset_password(s, row, panel)
        assert row.password_enc == old_enc and row.profile_synced is True  # the old password still works on the panel
        assert fake_adapter["a"].closed >= 1


async def test_a_crash_after_the_panel_changed_converges_through_the_worker(fake_adapter):
    """New secret saved + flagged, process dies before the final commit: the next sync pushes exactly that secret."""
    async with open_session() as s:
        main, r1, panel = await _world(s)
        await svc.sync_all(s)
        row = await s.scalar(select(PanelAdmin).where(PanelAdmin.store_id == r1.id))
        row.password_enc, row.profile_synced = svc.encrypt("Crash-Safe-Pass-12!"), False  # phase 1 of reset_password, then a crash
        await s.commit()
        assert (await svc.sync_all(s))["synced"] == 1
        assert fake_adapter["a"].admins[row.username] == "Crash-Safe-Pass-12!" and row.profile_synced is True


def test_migration_0041_follows_0040_and_guards_a_live_database():
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    f = Path(__file__).resolve().parents[2] / "alembic/versions/0041_panel_admin_guards.py"
    spec_ = importlib.util.spec_from_file_location("m0041", f)
    m = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(m)
    assert m.down_revision == "0040_panel_admins" and len(m.revision) <= 32

    def fresh():
        eng = sa.create_engine("sqlite://")
        with eng.begin() as c:
            c.execute(sa.text("CREATE TABLE panel_admins (id TEXT PRIMARY KEY, panel_id TEXT, store_id TEXT, username TEXT)"))
            c.execute(
                sa.text("CREATE TABLE panel_admin_change_requests (id TEXT PRIMARY KEY, store_id TEXT, status TEXT, created_at TEXT)")
            )
        return eng

    def run(eng, fn):
        with eng.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                fn()

    eng = fresh()
    with eng.begin() as c:  # two stores already share a login: the migration must stop, not guess
        c.execute(sa.text("INSERT INTO panel_admins VALUES ('1','p','s1','rs_x'), ('2','p','s2','rs_x')"))
    with pytest.raises(RuntimeError, match="share one panel login"):
        run(eng, m.upgrade)

    eng = fresh()
    with eng.begin() as c:
        c.execute(sa.text("INSERT INTO panel_admins VALUES ('1','p','s1','a'), ('2','p','s2','b'), ('3','q','s1','a')"))
        c.execute(
            sa.text(
                "INSERT INTO panel_admin_change_requests VALUES "
                "('r1','s1','pending','2026-11-01'), ('r2','s1','pending','2026-11-03'), ('r3','s1','pending','2026-11-02'),"
                "('r4','s2','pending','2026-11-01'), ('r5','s1','rejected','2026-10-01')"
            )
        )
    run(eng, m.upgrade)
    with eng.connect() as c:
        status = dict(c.execute(sa.text("SELECT id, status FROM panel_admin_change_requests")).fetchall())
        assert status == {"r1": "cancelled", "r2": "pending", "r3": "cancelled", "r4": "pending", "r5": "rejected"}
        indexes = {r[1] for r in c.execute(sa.text("PRAGMA index_list('panel_admins')")).fetchall()}
        assert "uq_panel_admins_panel_username" in indexes
    run(eng, m.downgrade)
    with eng.connect() as c:
        assert "uq_panel_admins_panel_username" not in {r[1] for r in c.execute(sa.text("PRAGMA index_list('panel_admins')")).fetchall()}
