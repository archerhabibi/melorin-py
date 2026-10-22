"""Live HTTP end-to-end smoke test (API + worker + PostgreSQL + Redis, mock VPN panel).

Usage: python scripts/e2e_smoke.py [base_url]   (env: E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD)
Exit code 0 only when the whole wallet -> order -> provisioning flow completes.
"""
import os
import sys
import time
import uuid

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
A = f"{BASE}/api/v1"
fails: list[str] = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        fails.append(name)
    return cond


def idem():
    return {"Idempotency-Key": uuid.uuid4().hex}


c = httpx.Client(timeout=30)
H = lambda t, **k: {"Authorization": f"Bearer {t}", **k}  # noqa: E731

for p in ("/health/live", "/health/ready"):
    check(f"GET {p}", c.get(BASE + p).status_code == 200)
def _admin_totp() -> str | None:
    """Current RFC 6238 code when E2E_ADMIN_TOTP_SECRET is set (super admins require a second factor)."""
    secret = os.getenv("E2E_ADMIN_TOTP_SECRET") or os.getenv("MELORIN_BOOTSTRAP_ADMIN_TOTP_SECRET")
    if not secret:
        return None
    import base64
    import hashlib
    import hmac
    import struct

    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


_login = {"email": os.getenv("E2E_ADMIN_EMAIL", "admin@example.com"), "password": os.getenv("E2E_ADMIN_PASSWORD", "Strong-admin-password-123456")}
if _admin_totp():
    _login["totp_code"] = _admin_totp()
r = c.post(f"{A}/auth/password/login", json=_login)
if not check("admin login", r.status_code == 200, r.text):
    sys.exit("RESULT: FAILED - cannot continue without an admin session")
adm = H(r.json()["access_token"])
store = c.get(f"{A}/stores/main").json()
sid = store["id"]
check("main store exists", bool(sid))

tag = uuid.uuid4().hex[:6]
r = c.post(f"{A}/admin/panels", headers=adm, json={"name": f"mock-{tag}", "kind": "mock", "base_url": "https://mock.example.com", "credentials": {}})
check("create mock panel", r.status_code in (200, 201), r.text); pid = r.json()["id"]
r = c.post(f"{A}/admin/servers", headers=adm, json={"name": f"srv-{tag}", "panel_id": pid, "capacity": 100})
check("create server", r.status_code in (200, 201), r.text)
r = c.post(f"{A}/admin/products", headers=adm, json={"code": f"P{tag}", "name": "Plan 30d", "duration_days": 30, "traffic_gb": 50, "main_price": 100000, "reseller_price": 70000, "currency": "IRT"})
check("create product", r.status_code in (200, 201), r.text); prod = r.json()["id"]
r = c.post(f"{A}/admin/bundles", headers=adm, json={"name": f"bundle-{tag}", "panel_ids": [pid]})
check("create sales bundle", r.status_code in (200, 201), r.text); gid = r.json()["id"]
r = c.put(f"{A}/admin/bundles/{gid}/products/{prod}", headers=adm, json={})
check("add package to bundle", r.status_code in (200, 201), r.text)
r = c.post(f"{A}/admin/products/{prod}/availability", headers=adm, json={"store_id": sid, "enabled": True})
check("enable product for main store", r.status_code in (200, 201), r.text)
c.put(f"{A}/admin/settings/card.info", headers=adm, json={"value": {"card_number": "6037000000000000", "holder": "Test"}})
r = c.post(f"{A}/admin/panels/{pid}/health", headers=adm)
check("panel health-check", r.status_code == 200 and r.json().get("healthy"), r.text)

cat = c.get(f"{A}/stores/{sid}/catalog").json()
items = cat if isinstance(cat, list) else cat.get("items", [])
check("catalog lists product", any(str(x.get("product_id")) == prod for x in items))

email = f"cust-{tag}@example.com"
r = c.post(f"{A}/auth/email/request-code", json={"email": email})
check("request code", r.status_code in (200, 202), r.text)
code = r.json().get("code") or r.json().get("dev_code")
r = c.post(f"{A}/auth/email/verify-code", json={"email": email, "code": code, "accept_terms_version": "1"})
check("customer login", r.status_code == 200, r.text)
cust = H(r.json()["access_token"])

r = c.post(f"{A}/stores/{sid}/orders", headers={**cust, **idem()}, json={"product_id": prod, "bundle_id": gid})
check("order with 0 balance -> 402", r.status_code == 402, f"{r.status_code} {r.text}")
r = c.post(f"{A}/stores/{sid}/orders", json={"product_id": prod, "bundle_id": gid})
check("order without auth -> 401", r.status_code == 401)
r = c.post(f"{A}/stores/{sid}/wallet/topups", headers={**cust, **idem()}, json={"amount": 150000, "provider": "manual_card"})
check("top-up request", r.status_code in (200, 201), r.text); pay = r.json().get("id") or r.json().get("payment", {}).get("id")
r = c.post(f"{A}/admin/payments/{pay}/review", headers=adm, json={"approve": True})
check("admin approves top-up", r.status_code == 200, r.text)
w = c.get(f"{A}/stores/{sid}/wallet", headers=cust).json()
check("wallet = 150000", w.get("balance") == 150000, str(w))
r = c.post(f"{A}/stores/{sid}/orders", headers={**cust, **idem()}, json={"product_id": prod, "bundle_id": gid})
check("order created", r.status_code in (200, 201), r.text); oid = r.json()["id"]
w = c.get(f"{A}/stores/{sid}/wallet", headers=cust).json()
check("wallet = 50000 after purchase", w.get("balance") == 50000, str(w))

status = None
for _ in range(40):
    status = c.get(f"{A}/stores/{sid}/orders/{oid}", headers=cust).json().get("status")
    if status in ("completed", "manual_review", "failed"):
        break
    time.sleep(1)
if status == "manual_review":
    c.post(f"{A}/admin/orders/{oid}/retry", headers=adm)
    for _ in range(40):
        status = c.get(f"{A}/stores/{sid}/orders/{oid}", headers=cust).json().get("status")
        if status in ("completed", "failed"):
            break
        time.sleep(1)
check("order completed via worker", status == "completed", str(status))
accts = c.get(f"{A}/stores/{sid}/vpn-accounts", headers=cust).json()
accts = accts if isinstance(accts, list) else accts.get("items", [])
check("exactly one VPN account for the order", len(accts) == 1, str(len(accts)))
check("customer -> admin endpoint 403", c.get(f"{A}/admin/users", headers=cust).status_code == 403)
check("no token -> admin 401", c.get(f"{A}/admin/users").status_code == 401)
# Channel binding: the customer's session belongs to the main store only; an admin account never gets a store session.
r = c.get(f"{A}/stores/{uuid.uuid4()}/wallet", headers=cust)
check("customer token on another store -> 403 CHANNEL_MISMATCH", r.status_code == 403 and r.json()["error"]["code"] == "CHANNEL_MISMATCH", r.text)
r = c.get(f"{A}/me/stores", headers=cust)
check("customer sees only the store of his session", r.status_code == 200 and [x["id"] for x in r.json()] == [sid], r.text)
admin_email = _login["email"]
r = c.post(f"{A}/auth/email/request-code", json={"email": admin_email})
admin_code = r.json().get("code") or r.json().get("dev_code")
r = c.post(f"{A}/auth/email/verify-code", json={"email": admin_email, "code": admin_code, "accept_terms_version": "1"})
check("admin via email code -> ADMIN_USE_PANEL (no admin session)", r.status_code == 403 and r.json()["error"]["code"] == "ADMIN_USE_PANEL", r.text)
time.sleep(5)
r = c.get(BASE + "/health/ready").json()
check("outbox drains (pending == 0)", r.get("outbox_pending") == 0, str(r))
check("worker heartbeat ok", r.get("worker") == "ok", str(r))
for i in range(40):
    r = c.post(f"{A}/auth/password/login", headers={"X-Forwarded-For": f"9.9.{i}.1"}, json={"email": "nobody@example.com", "password": "wrong-password-1"})
    if r.status_code == 429:
        break
check("login brute force throttled despite rotating XFF", r.status_code == 429, str(r.status_code))
print("\nRESULT:", "FAILED: " + ", ".join(fails) if fails else "ALL PASSED")
sys.exit(1 if fails else 0)
