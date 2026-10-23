"""Plan browsing, quote, coupon and wallet purchase flow."""

import logging
import re

from tgmain.ui import (
    PAGE_SIZE,
    b64,
    esc,
    fmt,
    unb64,
)

log = logging.getLogger("melorin.telegram.main")


class PlansMixin:
    """Plan browsing, quote, coupon and wallet purchase flow."""

    async def bundles(self) -> list:
        store = await self.store_info()
        r = await self.client.get(f"{self.core}/api/v1/stores/{store['id']}/bundles")
        r.raise_for_status()
        return r.json()

    async def cmd_plans(self, ctx, arg):
        self._merge_state(ctx.chat_id, flow=None, coupon=None, coupon_for=None)
        bundles = await self.bundles()
        if not bundles:
            return await self.screen(ctx, "فعلاً سرویسی برای فروش موجود نیست.", [[("↩︎ بازگشت", "menu:home")]])
        if len(bundles) == 1:
            return await self.choose_bundle(ctx, bundles[0], multi=False)
        rows = [[(f"{p.get('kind_label') or ''} · {p['name']}".strip(" ·"), f"bundle:{p['id']}")] for p in bundles]
        rows.append([("↩︎ بازگشت", "menu:home")])
        await self.screen(ctx, "🛒 <b>خرید اکانت</b>\nنوع سرویس را انتخاب کنید:", rows)

    async def choose_bundle(self, ctx, bundle, *, multi: bool):
        flow = {"bundle": bundle["id"], "pname": bundle["name"], "naming": bundle.get("naming_mode") or "automatic", "multi": multi}
        self._merge_state(ctx.chat_id, flow=flow, coupon=None, coupon_for=None)
        panels = bundle.get("panels") or []
        if not panels:
            return await self.show_plans(ctx, 0)
        rows = [[(str(x["label"]), f"pnl:{x['id']}")] for x in panels]
        rows.append([("↩︎ بازگشت", "menu:plans" if multi else "menu:home")])
        await self.screen(ctx, "📍 یکی از گزینه‌ها را انتخاب کنید:", rows)

    async def cb_bundle(self, ctx, bundle_id):
        bundle = next((p for p in await self.bundles() if p["id"] == bundle_id), None)
        if bundle is None:
            return await self.cmd_plans(ctx, "")
        await self.choose_bundle(ctx, bundle, multi=True)

    async def cb_panel(self, ctx, panel_id):
        flow = self._flow(ctx)
        bundle = next((p for p in await self.bundles() if p["id"] == flow.get("bundle")), None)
        panel = next((x for x in (bundle or {}).get("panels") or [] if x["id"] == panel_id), None)
        if panel is None:
            return await self.cmd_plans(ctx, "")
        self._merge_state(ctx.chat_id, flow={**flow, "panel": panel["id"], "plabel": panel["label"]})
        await self.show_plans(ctx, 0)

    async def cb_plans(self, ctx, page):
        await self.show_plans(ctx, int(page) if page.isdigit() else 0)

    async def show_plans(self, ctx, page: int, *, renew: str | None = None):
        flow = self._flow(ctx)
        if renew:
            items = await self.api(ctx, "GET", f"/api/v1/stores/{(await self.store_info())['id']}/accounts/{unb64(renew)}/renewal-packages")
        elif not flow.get("bundle"):
            return await self.cmd_plans(ctx, "")
        else:
            store = await self.store_info()
            r = await self.client.get(f"{self.core}/api/v1/stores/{store['id']}/bundles/{flow['bundle']}/packages")
            r.raise_for_status()
            items = r.json()
        if not items:
            return await self.screen(
                ctx, "فعلاً سرویسی برای فروش موجود نیست.", [[("↩︎ بازگشت", f"account:{unb64(renew)}" if renew else "menu:home")]]
            )
        pages = max(1, -(-len(items) // PAGE_SIZE))
        page = min(max(page, 0), pages - 1)
        chunk = items[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
        pick = (lambda pid: f"rnq:{renew}:{b64(pid)}") if renew else (lambda pid: f"plan:{pid}")
        rows = [[(f"{p['name']} · {fmt(p['price'], p['currency'])}", pick(p["product_id"]))] for p in chunk]
        if pages > 1 and not renew:
            rows.append(
                [
                    ("‹ قبلی", f"plans:{page - 1}") if page else ("·", "noop"),
                    (f"{page + 1}/{pages}", "noop"),
                    ("بعدی ›", f"plans:{page + 1}") if page < pages - 1 else ("·", "noop"),
                ]
            )
        if renew:
            rows.append([("↩︎ بازگشت به اکانت", f"account:{unb64(renew)}")])
        else:
            rows.append(
                [("↩︎ بازگشت", f"bundle:{flow['bundle']}" if flow.get("panel") else "menu:plans" if flow.get("multi") else "menu:home")]
            )
        head = f"\n📦 {esc(flow.get('pname'))}" if flow.get("pname") and not renew else ""
        title = (
            "🔄 <b>تمدید اکانت</b>\nسرویس موردنظر برای تمدید را انتخاب کنید:"
            if renew
            else f"🛒 <b>خرید اکانت</b>{head}\nیک سرویس انتخاب کنید:"
        )
        await self.screen(ctx, title, rows)

    async def cb_plan(self, ctx, pid):
        flow = self._flow(ctx)
        self._merge_state(ctx.chat_id, coupon=None, coupon_for=None)
        if flow.get("naming") == "custom":
            self._merge_state(ctx.chat_id, flow={**flow, "name": None, "ask": pid})
            return await self.screen(
                ctx, "✍️ نام کاربری دلخواه اکانت را بفرستید (حداقل ۳ حرف انگلیسی/عدد/_/-).\nیا برای نام‌گذاری خودکار دکمهٔ زیر را بزنید:",
                [[("🔄 نام خودکار", f"an:{pid}")], [("↩︎ بازگشت", "plans:0")]],
            )
        await self.show_quote(ctx, pid)

    async def cb_autoname(self, ctx, pid):
        """The customer skips the custom name: the account is named automatically, exactly like an automatic bundle."""
        self._merge_state(ctx.chat_id, flow={**self._flow(ctx), "name": None, "ask": None})
        await self.show_quote(ctx, pid)

    async def set_account_name(self, ctx, pid, text: str):
        name = re.sub(r"[^A-Za-z0-9_-]", "", text)[:40]
        if len(name) < 3:
            return await self.send(ctx.chat_id, "نام نامعتبر است. حداقل ۳ حرف انگلیسی/عدد/_/- بفرستید:")
        self._merge_state(ctx.chat_id, flow={**self._flow(ctx), "name": name, "ask": None})
        await self.show_quote(ctx, pid)

    async def cb_quote(self, ctx, pid):
        await self.show_quote(ctx, pid)

    def _alloc(self, ctx) -> dict:
        f = self._flow(ctx)
        body = {"bundle_id": f["bundle"]} if f.get("bundle") else {}
        if f.get("panel"):
            body["selected_panel_id"] = f["panel"]
        return body

    async def show_quote(self, ctx, pid, *, coupon: str | None = None, renew: str | None = None):
        """One card: what you buy, price, discount, wallet balance BEFORE and AFTER, and the right next button."""
        store = await self.store_info()
        flow = {} if renew else self._flow(ctx)
        body = {"product_id": pid, "vpn_account_id": unb64(renew)} if renew else {"product_id": pid, **self._alloc(ctx)}
        if coupon:
            body["coupon_code"] = coupon
        q = await self.api(ctx, "POST", f"/api/v1/stores/{store['id']}/checkout/quote", json=body)
        c = q["currency"]
        lines = ["🔄 <b>تمدید اکانت</b>" if renew else "🧾 <b>پیش‌فاکتور</b>", ""]
        if flow.get("pname"):
            lines.append(f"📦 سرویس: {esc(flow['pname'])}")
        if flow.get("plabel"):
            lines.append(f"📍 {esc(flow['plabel'])}")
        if flow.get("name"):
            lines.append(f"👤 نام کاربری: <code>{esc(flow['name'])}</code>")
        if renew and q.get("renewal"):
            r = q["renewal"]
            vol = f"{r['traffic_gb']} GB" if r.get("traffic_gb") else "نامحدود"
            lines.append(f"⏳ پس از تمدید: {r['duration_days']} روز · {vol} (مثل یک اکانت جدید همین پکیج)")
            if r.get("remaining_days_replaced"):
                lines.append(f"ℹ️ {r['remaining_days_replaced']} روز باقی‌مانده فعلی جایگزین می‌شود و به آن اضافه نمی‌شود.")
        lines.append(f"💵 قیمت: {esc(fmt(q['unit_price'], c))}")
        if q.get("discount"):
            tag = f" ({esc(q.get('coupon_code'))})" if q.get("coupon_code") else ""
            lines.append(f"🏷 تخفیف{tag}: {esc(fmt(q['discount'], c))}")
        lines.append(f"💰 مبلغ نهایی: <b>{esc(fmt(q['total'], c))}</b>")
        balance = int(q.get("wallet_balance") or 0)
        lines += ["", f"👛 موجودی کیف پول: {esc(fmt(balance, c))}"]
        if q.get("sufficient_funds"):
            lines.append(f"📉 موجودی پس از پرداخت: <b>{esc(fmt(balance - int(q['total']), c))}</b>")
            if coupon:
                self._merge_state(ctx.chat_id, coupon={"pid": str(pid), "code": coupon})
            go = f"rnb:{renew}:{b64(pid)}" if renew else f"buy:{pid}"
            rows = [[("✅ تأیید و پرداخت از کیف پول", go)]]
        else:
            short = int(q["total"]) - balance
            lines.append(f"⚠️ موجودی کافی نیست؛ <b>{esc(fmt(short, c))}</b> کم دارید.")
            rows = [[(f"💳 شارژ {fmt(short, c)}", f"wallet:amount:{short}")]]
        if not renew:
            rows.append([("🎟 کد تخفیف", f"cpn:{pid}")])
        rows.append([("↩︎ بازگشت", f"account:{unb64(renew)}" if renew else "plans:0")])
        await self.screen(ctx, "\n".join(lines), rows)

    async def cb_coupon(self, ctx, pid):
        self._merge_state(ctx.chat_id, coupon_for=pid)
        await self.screen(ctx, "🎟 کد تخفیف را بفرستید:", [[("↩︎ بازگشت", f"qt:{pid}")]])

    def _coupon_for(self, ctx, pid) -> str | None:
        c = (self.state.get(str(ctx.chat_id)) or {}).get("coupon") or {}
        return c.get("code") if c.get("pid") == str(pid) else None

    async def cb_buy(self, ctx, pid):
        store = await self.store_info()
        flow = self._flow(ctx)
        body = {"product_id": pid, "payment_method": "wallet", "kind": "purchase", **self._alloc(ctx)}
        if flow.get("naming") == "custom" and flow.get("name"):
            body["account_name"] = flow["name"]
        if self._coupon_for(ctx, pid):
            body["coupon_code"] = self._coupon_for(ctx, pid)
        o = await self.api(ctx, "POST", f"/api/v1/stores/{store['id']}/orders", headers={"Idempotency-Key": ctx.idem}, json=body)
        self._set_state(ctx.chat_id, None)
        await self.order_done(ctx, o, "✅ <b>پرداخت از کیف پول انجام شد</b>")

    async def order_done(self, ctx, o, title: str):
        paid = f"\n💰 مبلغ پرداختی: {esc(fmt(o['total'], o.get('currency')))}" if o.get("total") is not None else ""
        await self.screen(
            ctx,
            f"{title}\n\n📦 سفارش: <code>{esc(o['number'])}</code>{paid}\n"
            "⚙️ اکانت شما در چند لحظه ساخته و همین‌جا ارسال می‌شود "
            "(لینک اشتراک، QR کد و موجودی کیف پول).",
            [[("🔑 اکانت‌های من", "menu:accounts")]],
        )
