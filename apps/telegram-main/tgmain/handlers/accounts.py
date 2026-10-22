"""Account inquiry (list/search/card/QR), renewal and test accounts - own accounts only; reseller owners see their customers'."""

import logging

from tgmain.ui import (
    ACC_FILTERS,
    HEALTH_BADGE,
    HEALTH_LABEL,
    PAGE_SIZE,
    b64,
    esc,
    expiry_line,
    fmt,
    qr_png,
    unb64,
    usage_bar,
)
from tgmain.errors import CoreError

log = logging.getLogger("melorin.telegram.main")


def _list_head(cfg: dict, counts: dict, q, filtered: bool, rows: list) -> list[str]:
    """Header lines of the account list: totals, active search, Core's own note, and the hint (or empty-state text)."""
    head = [
        f"{cfg['title']} · {counts.get('total', 0)} اکانت",
        f"🟢 {counts.get('active', 0)} فعال · 🟡 {counts.get('expiring', 0)} رو‌به‌اتمام · 🔴 {counts.get('expired', 0)} منقضی",
    ]
    if q:
        head.append(f"🔎 جستجو: «{esc(q)}»")
    if cfg["owner"] and not q and counts.get("note"):  # Core's own words about what this list is
        head.append(f"ℹ️ {esc(counts['note'])}")
    if not rows:
        head += ["", "نتیجه‌ای پیدا نشد." if (q or filtered) else "هنوز اکانتی نساخته‌اید."]
    elif cfg["owner"]:
        head += ["", "برای دیدن جزئیات، تمدید یا QR یکی را انتخاب کنید:"]
    else:
        head += ["", "برای مشاهده، تمدید یا QR کد یکی را انتخاب کنید:"]
    return head


def _account_button(cfg: dict, a: dict) -> list[tuple[str, str]]:
    left = a.get("days_left")
    tail = f" · {left}ر" if left is not None else " · ♾"
    who = f" · {a['customer_name'][:14]}" if cfg["owner"] and not a.get("is_own") and a.get("customer_name") else ""
    return [(f"{HEALTH_BADGE.get(a.get('health'), '•')} {a['username']}{tail}{who}", f"{'o' if cfg['owner'] else ''}account:{a['id']}")]


def _list_buttons(cfg: dict, counts: dict, code: str, q, rows: list, page: int, more: bool) -> list:
    """Filter chips, one button per account, paging, search controls and (customers only) the way back to the menu."""
    pre = "o" if cfg["owner"] else ""
    chips = [(f"{'✓ ' if c == code else ''}{label} ({counts.get(st or 'total', 0)})", f"{pre}acl:{c}:0") for c, st, label in ACC_FILTERS]
    buttons = [chips[:2], chips[2:]]
    buttons += [_account_button(cfg, a) for a in rows]
    nav = []
    if page > 0:
        nav.append(("◀️ قبلی", f"{pre}acl:{code}:{page - 1}"))
    if more:
        nav.append(("بعدی ▶️", f"{pre}acl:{code}:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([("🔎 جستجو" + (" (تغییر)" if q else ""), f"{pre}acs:1")] + ([("✖️ پاک‌کردن جستجو", f"{pre}acq:1")] if q else []))
    if not cfg["owner"]:
        buttons.append([("🏠 بازگشت به منو", "menu:home")])
    return buttons


class AccountsMixin:
    """Account inquiry (list/search/card/QR), renewal and test accounts - own accounts only; reseller owners see their customers'."""

    # All numbers come from Core, which reads them from the VPN panel; the bot never computes expiry/usage itself.
    ACC_SCOPES = {
        "me": {"list": "vpn-accounts", "title": "🔑 <b>اکانت‌های من</b>", "key": "accv", "owner": False},
        "ow": {"list": "reseller/accounts", "title": "🗂 <b>اکانت‌های نماینده</b>", "key": "oaccv", "owner": True},
    }

    async def _acc_base(self, scope: str) -> str:
        # Both audiences are store-scoped in Core: the customer's own accounts of THIS bot's store, or the owner's store view.
        return f"/api/v1/stores/{(await self.store_info())['id']}/{self.ACC_SCOPES[scope]['list']}"

    def _acc_view(self, ctx, scope: str) -> dict:
        return dict((self.state.get(str(ctx.chat_id)) or {}).get(self.ACC_SCOPES[scope]["key"]) or {})

    def _acc_set_view(self, ctx, scope: str, **kw) -> dict:
        view = {**self._acc_view(ctx, scope), **kw}
        self._merge_state(ctx.chat_id, **{self.ACC_SCOPES[scope]["key"]: {k: v for k, v in view.items() if v not in (None, "")} or None})
        return view

    async def cmd_accounts(self, ctx, arg):
        self._merge_state(ctx.chat_id, acc_search=None)
        self._acc_set_view(ctx, "me", f=None, q=None, p=None)
        await self.show_accounts(ctx, "me")

    async def show_accounts(self, ctx, scope: str):
        cfg, view = self.ACC_SCOPES[scope], self._acc_view(ctx, scope)
        code = view.get("f") or "-"
        state = next((st for c, st, _ in ACC_FILTERS if c == code), None)
        page, q = max(0, int(view.get("p") or 0)), view.get("q")
        base = await self._acc_base(scope)
        params = {"limit": PAGE_SIZE + 1, "offset": page * PAGE_SIZE}
        if state:
            params["state"] = state
        if q:
            params["q"] = q
        counts = await self.api(ctx, "GET", f"{base}/summary")
        rows = await self.api(ctx, "GET", base, params=params)
        more, rows = len(rows) > PAGE_SIZE, rows[:PAGE_SIZE]
        if not counts.get("total") and not q and not cfg["owner"]:
            return await self.screen(
                ctx, "🔑 هنوز اکانتی ندارید.", [[("🛒 خرید اکانت", "menu:plans")], [("🧪 دریافت اکانت تست", "menu:test")]]
            )
        head = _list_head(cfg, counts, q, bool(state), rows)
        buttons = _list_buttons(cfg, counts, code, q, rows, page, more)
        await self.screen(ctx, "\n".join(head + (["", f"صفحه {page + 1}"] if page or more else [])), buttons)

    async def cb_acc_list(self, ctx, value, scope: str = "me"):
        code, _, page = value.partition(":")
        if code not in {c for c, _, _ in ACC_FILTERS}:
            code = "-"
        self._merge_state(ctx.chat_id, acc_search=None)
        self._acc_set_view(ctx, scope, f=None if code == "-" else code, p=int(page) if page.isdigit() else 0)
        await self.show_accounts(ctx, scope)

    async def cb_acc_search(self, ctx, _, scope: str = "me"):
        self._merge_state(ctx.chat_id, acc_search=scope)
        who = "نام اکانت، نام یا ایمیل مشتری" if self.ACC_SCOPES[scope]["owner"] else "نام اکانت"
        await self.send(ctx.chat_id, f"🔎 {who} (یا بخشی از آن) را بفرستید:\nبرای انصراف /cancel")

    async def cb_acc_clear(self, ctx, _, scope: str = "me"):
        self._merge_state(ctx.chat_id, acc_search=None)
        self._acc_set_view(ctx, scope, q=None, p=None)
        await self.show_accounts(ctx, scope)

    async def acc_apply_search(self, ctx, scope: str, text: str):
        self._merge_state(ctx.chat_id, acc_search=None)  # one-shot: the next message is never read as a search again
        term = text.strip()[:64]
        self._acc_set_view(ctx, scope, q=term or None, p=None, f=None)
        await self.show_accounts(ctx, scope)

    async def show_account_card(self, ctx, account_id: str, scope: str = "me"):
        owner = self.ACC_SCOPES[scope]["owner"]
        base = await self._acc_base(scope)
        back = f"{'o' if owner else ''}acl:{(self._acc_view(ctx, scope).get('f') or '-')}:{int(self._acc_view(ctx, scope).get('p') or 0)}"
        try:  # live numbers straight from the VPN panel (Core rate-limits it per account and keeps the last values if the panel is down)
            account = await self.api(ctx, "POST", f"{base}/{account_id}/refresh")
        except CoreError as exc:
            if exc.status != 404:
                raise
            return await self.screen(ctx, "این اکانت دیگر در دسترس نیست.", [[("↩︎ بازگشت", back)]])
        link = account.get("subscription_url")
        health = account.get("health")
        lines = [
            f"👤 <b>{esc(account.get('username', '-'))}</b>",
            f"وضعیت: {HEALTH_BADGE.get(health, '•')} {HEALTH_LABEL.get(health, esc(account.get('status')))}",
        ]
        if owner:
            lines.append(f"🙋 {esc(account.get('holder_label') or account.get('customer_name') or '-')}")
        lines += [
            expiry_line(account.get("expires_at")),
            "",
            f"📊 {usage_bar(account.get('traffic_used_bytes'), account.get('traffic_limit_bytes'))}",
        ]
        lines += ["", "🔗 لینک اشتراک (برای کپی لمس کنید):", f"<code>{esc(link)}</code>"] if link else ["", "🔗 لینک در حال آماده‌سازی است."]
        pre = "o" if owner else ""
        action = []
        if link:
            action.append(("📷 QR کد", f"{pre}qr:{b64(account['id'])}"))
        if account.get("can_renew"):  # Core decides (up to 10 days after expiry); the bot never re-implements the rule
            action.append(("🔄 تمدید", f"{'orn' if owner else 'rnw'}:{b64(account['id'])}"))
        rows = ([action] if action else []) + [[("🔃 بروزرسانی از پنل", f"{pre}account:{account['id']}")], [("↩︎ بازگشت به لیست", back)]]
        await self.screen(ctx, "\n".join(lines), rows)

    async def cb_account(self, ctx, value):
        await self.show_account_card(ctx, value, "me")

    async def _find_account(self, ctx, account_id, scope: str = "me"):
        try:
            return await self.api(ctx, "GET", f"{await self._acc_base(scope)}/{account_id}")
        except CoreError as exc:
            if exc.status == 404:
                return None
            raise

    async def cb_qr(self, ctx, token, scope: str = "me"):
        account = await self._find_account(ctx, unb64(token), scope)
        link = (account or {}).get("subscription_url")
        if not link:
            raise CoreError(404, "لینک اشتراک این اکانت هنوز آماده نیست.")
        png = qr_png(link)
        caption = f"📷 QR کد اشتراک <b>{esc(account['username'])}</b>\n\n<code>{esc(link)}</code>"
        if png:
            await self.send_photo(ctx.chat_id, png, caption)
        else:
            await self.send(ctx.chat_id, f"🔗 <code>{esc(link)}</code>", html=True)

    async def cb_renew(self, ctx, token):
        """A renewal is the account's own package at its current price: Core says whether it may be renewed and with what."""
        acc = unb64(token)  # validate early
        store = await self.store_info()
        info = await self.api(ctx, "GET", f"/api/v1/stores/{store['id']}/accounts/{acc}/renewal")
        if not info.get("renewable"):
            return await self.screen(
                ctx,
                f"⚠️ {esc(info.get('message') or 'این اکانت قابل تمدید نیست.')}",
                [[("🛒 خرید اکانت جدید", "menu:plans")], [("↩︎ بازگشت به اکانت", f"account:{acc}")]],
            )
        await self.show_quote(ctx, info["package"]["product_id"], renew=token)

    async def cb_renew_quote(self, ctx, rest):
        acc, _, pid = rest.partition(":")
        unb64(acc)
        await self.show_quote(ctx, unb64(pid), renew=acc)

    async def cb_renew_buy(self, ctx, rest):
        acc, _, pid = rest.partition(":")
        store = await self.store_info()
        o = await self.api(
            ctx,
            "POST",
            f"/api/v1/stores/{store['id']}/orders",
            headers={"Idempotency-Key": ctx.idem},
            json={"product_id": unb64(pid), "payment_method": "wallet", "kind": "renewal", "vpn_account_id": unb64(acc)},
        )
        await self.order_done(ctx, o, "✅ <b>تمدید با کیف پول پرداخت شد</b>")

    # ----- the reseller renews his own accounts and HIS OWN store's customers' accounts (Core: anyone else -> 404) -----
    async def cb_owner_renew(self, ctx, token):
        acc = unb64(token)
        base = await self._acc_base("ow")
        info = await self.api(ctx, "GET", f"{base}/{acc}/renewal")
        back = [("↩︎ بازگشت به اکانت", f"oaccount:{acc}")]
        if not info.get("renewable"):
            return await self.screen(ctx, f"⚠️ {esc(info.get('message') or 'این اکانت قابل تمدید نیست.')}", [back])
        pkg, after = info["package"], info.get("after") or {}
        lines = ["🔄 <b>تمدید اکانت</b>", "", f"📦 {esc(pkg.get('name'))}", f"💰 مبلغ: <b>{esc(fmt(pkg['price'], pkg['currency']))}</b>"]
        if after:
            volume = f"{after['traffic_gb']} گیگ" if after.get("traffic_gb") else "نامحدود"
            lines.append(f"پس از تمدید: {after.get('duration_days')} روز · {volume} (روزهای باقی‌مانده فعلی جایگزین می‌شود، اضافه نمی‌شود)")
        if info.get("payer_note"):
            lines.append(esc(info["payer_note"]))
        await self.screen(ctx, "\n".join(lines), [[("✅ تأیید و تمدید", f"orb:{token}")], back])

    async def cb_owner_renew_buy(self, ctx, token):
        acc = unb64(token)
        base = await self._acc_base("ow")
        await self.api(ctx, "POST", f"{base}/{acc}/renew", headers={"Idempotency-Key": ctx.idem}, json={"channel": "telegram"})
        await self.send(ctx.chat_id, "✅ تمدید ثبت شد؛ به‌محض اعمال روی پنل، اکانت بروزرسانی می‌شود.")
        await self.show_account_card(ctx, acc, "ow")

    async def cmd_test(self, ctx, arg):
        store = await self.store_info()
        o = await self.api(ctx, "POST", f"/api/v1/stores/{store['id']}/test-account")
        await self.send(ctx.chat_id, f"🧪 اکانت تست ساخته شد ({o['number']}). لینک و QR کد همین‌جا ارسال می‌شود.")
