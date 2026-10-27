"""Sign in with Google: ID tokens are verified locally against Google's public keys and bound to a nonce cookie."""

import time
import types

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Response

import melorin.models  # noqa: F401  (registers every table so FKs resolve)
from melorin.core import config as config_mod
from melorin.core import db, integrations, settings_store
from melorin.core.errors import AppError
from melorin.modules.admin import integrations as admin_integrations
from melorin.modules.identity import google as google_signin, router
from melorin.kernel.models.identity import Identity, IdentityLinkReview, RefreshToken, User
from melorin.modules.identity.schemas import GoogleLogin
from melorin.kernel.models.stores import Store
from melorin.kernel.models.system import AuditEvent, SecurityEvent, SystemSetting

CLIENT_ID = "123456789012-abc123def456.apps.googleusercontent.com"
TABLES = [
    User.__table__,
    Identity.__table__,
    RefreshToken.__table__,
    IdentityLinkReview.__table__,
    AuditEvent.__table__,
    SecurityEvent.__table__,
    SystemSetting.__table__,
    Store.__table__,
]
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key=KEY, kid="k1", alg="RS256", **over):
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "g-1",
        "iat": now,
        "exp": now + 3600,
        "email": "u@example.com",
        "email_verified": True,
        "nonce": "n1",
    }
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


@pytest.fixture(autouse=True)
def google_keys(monkeypatch):
    """Serve Google's key set from memory; count fetches so caching/rotation can be asserted."""
    calls = types.SimpleNamespace(n=0, keys={"k1": KEY.public_key()})

    async def fake_load(force: bool = False):
        calls.n += 1
        return calls.keys

    monkeypatch.setattr(google_signin, "_load_google_keys", fake_load)
    return calls


async def test_valid_token_is_accepted_and_returns_claims():
    claims = await google_signin.verify_google_token(_token(), CLIENT_ID)
    assert claims["sub"] == "g-1" and claims["email"] == "u@example.com"


@pytest.mark.parametrize(
    "over,why",
    [
        ({"aud": "someone-else"}, "wrong audience"),
        ({"iss": "https://evil.example"}, "wrong issuer"),
        ({"exp": int(time.time()) - 600}, "expired"),
        ({"exp": None}, "missing exp"),
        ({"sub": None}, "missing sub"),
    ],
)
async def test_invalid_claims_are_rejected(over, why):
    with pytest.raises(AppError) as e:
        await google_signin.verify_google_token(_token(**over), CLIENT_ID)
    assert e.value.code == "GOOGLE_INVALID", why


async def test_bad_signature_alg_and_kid_are_rejected():
    for tok in (
        _token(key=OTHER_KEY),  # signed by someone else
        _token(kid="unknown"),  # unknown key id
        jwt.encode(
            {"sub": "x", "aud": CLIENT_ID}, "secret-secret-secret-secret-secret-32", algorithm="HS256", headers={"kid": "k1"}
        ),  # alg confusion
        jwt.encode({"sub": "x"}, None, algorithm="none"),  # unsigned
        "not-a-jwt",
    ):
        with pytest.raises(AppError) as e:
            await google_signin.verify_google_token(tok, CLIENT_ID)
        assert e.value.code == "GOOGLE_INVALID"


async def test_empty_client_id_is_refused():
    with pytest.raises(AppError) as e:
        await google_signin.verify_google_token(_token(), "")
    assert e.value.code == "GOOGLE_DISABLED"


async def test_unknown_kid_triggers_one_forced_key_refresh(monkeypatch):
    seen = []

    async def load(force: bool = False):
        seen.append(force)
        return {"k1": KEY.public_key()} if force else {}

    monkeypatch.setattr(google_signin, "_load_google_keys", load)
    assert (await google_signin.verify_google_token(_token(), CLIENT_ID))["sub"] == "g-1"
    assert seen == [False, True]


async def test_real_key_loader_caches_and_survives_an_outage(monkeypatch):
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True) | {"kid": "k1", "alg": "RS256", "use": "sig"}
    state = types.SimpleNamespace(fetches=0, down=False)

    class R:
        headers = {"cache-control": "public, max-age=3600"}

        def raise_for_status(self):
            pass

        def json(self):
            return {"keys": [jwk]}

    class C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            state.fetches += 1
            if state.down:
                raise google_signin.httpx.ConnectError("down")
            return R()

    monkeypatch.undo()  # use the real loader for this test
    monkeypatch.setattr(google_signin.httpx, "AsyncClient", lambda **k: C())
    monkeypatch.setitem(google_signin._google_keys, "keys", {})
    monkeypatch.setitem(google_signin._google_keys, "expires", 0.0)
    monkeypatch.setitem(google_signin._google_keys, "fetched", 0.0)
    assert "k1" in await google_signin._load_google_keys()
    await google_signin._load_google_keys()
    assert state.fetches == 1  # second call served from cache
    state.down = True
    google_signin._google_keys["expires"] = 0.0  # cache expired while Google is unreachable: keep the last known keys
    assert "k1" in await google_signin._load_google_keys()
    monkeypatch.setitem(google_signin._google_keys, "keys", {})
    google_signin._google_keys["expires"] = 0.0
    with pytest.raises(AppError) as e:
        await google_signin._load_google_keys()
    assert e.value.code == "GOOGLE_UNREACHABLE"


# ---------------- nonce binding ----------------
@pytest.fixture
async def session(tmp_path, monkeypatch):
    monkeypatch.delenv("MELORIN_GOOGLE_CLIENT_ID", raising=False)
    config_mod.get_settings.cache_clear()
    db.configure(f"sqlite+aiosqlite:///{tmp_path}/g.db")
    async with db.engine().begin() as conn:
        await conn.run_sync(lambda c: db.Base.metadata.create_all(c))
    async with db.session_factory()() as s:
        s.add(Store(kind="main", name="Main", slug="main"))
        await s.flush()
        await settings_store.set_value(
            s, integrations.GOOGLE_KEY, {"enabled": True, "client_id": CLIENT_ID, "admin_login": True, "store_login": True}
        )
        u = User(display_name="C", email="c@example.com")
        s.add(u)
        await s.flush()
        s.add(Identity(user_id=u.id, provider="google", subject="g-1", data={}))
        await s.commit()
        yield s
    await db.engine().dispose()
    config_mod.get_settings.cache_clear()


def _req(nonce):
    return types.SimpleNamespace(
        headers={"user-agent": "pytest", "host": "localhost"},
        client=types.SimpleNamespace(host="203.0.113.9"),
        cookies={router.GOOGLE_NONCE_COOKIE: nonce} if nonce else {},
    )


async def test_nonce_endpoint_sets_httponly_cookie_and_returns_same_value():
    resp = Response()
    out = await router.google_nonce(resp)
    cookie = resp.headers["set-cookie"].lower()
    assert (
        router.GOOGLE_NONCE_COOKIE in cookie and "httponly" in cookie and "samesite=lax" in cookie and "path=/api/v1/auth/google" in cookie
    )
    assert out["nonce"] in resp.headers["set-cookie"] and len(out["nonce"]) >= 24
    assert resp.headers["cache-control"] == "no-store"
    assert (await router.google_nonce(Response()))["nonce"] != out["nonce"]


async def test_login_succeeds_with_matching_nonce_and_consumes_the_cookie(session):
    resp = Response()
    pair = await router.google_login(GoogleLogin(id_token=_token()), session, _req("n1"), resp)
    assert pair.access_token
    cookies = resp.headers.getlist("set-cookie")
    assert any(
        c.startswith(f'{router.GOOGLE_NONCE_COOKIE}=""') or (c.startswith(router.GOOGLE_NONCE_COOKIE) and "Max-Age=0" in c) for c in cookies
    )


@pytest.mark.parametrize("cookie_nonce,token_nonce", [(None, "n1"), ("n1", "other"), ("n1", None), ("", "n1")])
async def test_login_is_refused_without_a_matching_nonce(session, cookie_nonce, token_nonce):
    with pytest.raises(AppError) as e:
        await router.google_login(GoogleLogin(id_token=_token(nonce=token_nonce)), session, _req(cookie_nonce), Response())
    assert e.value.code == "GOOGLE_NONCE_INVALID" and e.value.status == 401


async def test_admin_connectivity_test_uses_the_public_key_endpoint(session, monkeypatch):
    asked = []

    class R:
        status_code = 200

        def json(self):
            return {"keys": [{"kid": "k1"}]}

    class C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **k):
            asked.append(url)
            return R()

    monkeypatch.setattr(admin_integrations.httpx, "AsyncClient", lambda **k: C())
    out = await admin_integrations.test_google(types.SimpleNamespace(id=None), session)
    assert out == {"ok": True, "error": None} and asked == ["https://www.googleapis.com/oauth2/v3/certs"]
