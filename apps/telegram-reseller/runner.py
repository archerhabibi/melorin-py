"""Reseller Telegram runner.

Same Core-authenticated transport as the main runner, bound to one reseller Store
(``MELORIN_STORE_SLUG``). Customers get the full storefront; Store owners get extra
commands (/report, /customers, /payments). Authorization is enforced by Core (403 for
non-owners); this process never holds infrastructure credentials or other stores' data.
"""
import os
import asyncio
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_here = Path(__file__).parent
_path = next(p for p in (_here / "telegram-main" / "runner.py", _here.parent / "telegram-main" / "runner.py") if p.exists())
_spec = spec_from_file_location("melorin_telegram_main_runner", _path)
_module = module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_module)
money, keyboard = _module.money, _module.keyboard

OWNER_HELP = "\n\nبخش نماینده:\n/report گزارش فروش\n/customers مشتریان\n/payments پرداخت‌های در انتظار تأیید\n/prices قیمت فروش محصولات"


class ResellerTelegramRunner(_module.TelegramRunner):
    channel = "reseller"

    def __init__(self, *, token: str | None = None, slug: str | None = None, state_suffix: str | None = None):
        os.environ["MELORIN_TELEGRAM_TOKEN"] = token or os.environ["MELORIN_TELEGRAM_RESELLER_TOKEN"]
        self.slug = slug or os.environ["MELORIN_STORE_SLUG"]
        if state_suffix:
            os.environ["MELORIN_TELEGRAM_OFFSET_FILE"] = f"/var/lib/melorin/reseller-{state_suffix}-offset.json"
        super().__init__()
        self.commands.update({"/report": self.cmd_report, "/customers": self.cmd_customers, "/payments": self.cmd_payments, "/prices": self.cmd_prices})
        self.callbacks["rv"] = self.cb_review
        self.callbacks["prc"] = self.cb_price_pick

    async def store_info(self) -> dict:
        if self.store is None:
            r = await self.client.get(f"{self.core}/api/v1/stores/by-slug/{self.slug}")
            r.raise_for_status()
            self.store = r.json()
        return self.store

    async def cmd_help(self, ctx, arg):
        await self.send(ctx.chat_id, _module.HELP + OWNER_HELP, _module.MENU)

    async def cmd_report(self, ctx, arg):
        s = await self.store_info()
        rep = await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/reseller/reports")
        lines = [f"{o['status']}: {o['count']} سفارش · فروش {money(o['total'])} · بها {money(o['reseller_cost'])}" for o in rep["orders"]]
        await self.send(ctx.chat_id, f"گزارش ({rep['currency']}):\n" + ("\n".join(lines) or "—"))

    async def cmd_customers(self, ctx, arg):
        s = await self.store_info()
        cs = await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/reseller/customers")
        lines = [f"{c.get('display_name') or c.get('email') or c['user_id'][:8]} · {c['status']}" for c in cs[:30]]
        await self.send(ctx.chat_id, f"مشتریان ({len(cs)}):\n" + ("\n".join(lines) or "—"))

    async def cmd_payments(self, ctx, arg):
        s = await self.store_info()
        ps = await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/reseller/payments")
        todo = [p for p in ps if p["status"] not in ("succeeded", "failed") and p.get("has_receipt")][:10]
        if not todo:
            return await self.send(ctx.chat_id, "پرداخت در انتظار تأییدی نیست.")
        for p in todo:
            await self.send(ctx.chat_id, f"پرداخت {money(p['amount'])} {p['currency']} · {p['provider']}",
                            [[("✅ تأیید", f"rv:{p['id']}:1"), ("❌ رد", f"rv:{p['id']}:0")]])

    # ---- retail prices: the reseller sets them for THIS store only; the core enforces the cost floor ----
    async def cmd_prices(self, ctx, arg):
        s = await self.store_info()
        rows = await self.api(ctx, "GET", f"/api/v1/stores/{s['id']}/reseller/prices")
        if not rows:
            return await self.send(ctx.chat_id, "محصولی برای قیمت‌گذاری در دسترس نیست.")
        mark = {"unset": "⚪️ تعیین نشده", "ok": "✅", "below_cost": "⚠️ زیر قیمت همکاری"}
        buttons = []
        for r in rows[:30]:
            price = money(r["customer_price"]) if r["customer_price"] else mark["unset"]
            buttons.append([(f"{r['name']} · {price} · حداقل {money(r['cost_floor'])}", f"prc:{r['product_id']}")])
        await self.send(ctx.chat_id, "💲 قیمت فروش به مشتریان شما. محصولی را انتخاب کنید تا قیمتش را عوض کنید.\nمحصول بدون قیمت یا با قیمت زیر حداقل به مشتری نمایش داده نمی‌شود.", buttons)

    async def cb_price_pick(self, ctx, pid):
        self._merge_state(ctx.chat_id, price_for=pid)
        await self.send(ctx.chat_id, "قیمت فروش جدید را به عدد (تومان) بفرستید. برای برداشتن قیمت، 0 بفرستید.")

    async def on_text(self, ctx, text):
        pid = (self.state.get(str(ctx.chat_id)) or {}).get("price_for")
        if not pid or text.startswith("/"):
            return await super().on_text(ctx, text)
        digits = "".join(ch for ch in text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")) if ch.isdigit())
        if not digits:  # not a number: the reseller moved on (menu button, other text)
            self._merge_state(ctx.chat_id, price_for=None)
            return await super().on_text(ctx, text)
        s = await self.store_info()
        try:
            out = await self.api(ctx, "PUT", f"/api/v1/stores/{s['id']}/reseller/prices/{pid}", json={"customer_price": int(digits)})
        except _module.CoreError as e:  # the state stays, so the reseller can send another number
            return await self.send(ctx.chat_id, f"{e.message if hasattr(e, 'message') else e}\nعدد دیگری بفرستید:")
        self._merge_state(ctx.chat_id, price_for=None)
        await self.send(ctx.chat_id, "قیمت برداشته شد؛ محصول به مشتری نمایش داده نمی‌شود." if not out.get("customer_price") else f"✅ قیمت فروش {money(out['customer_price'])} ثبت شد.")

    async def cb_review(self, ctx, rest):
        pid, _, flag = rest.partition(":")
        s = await self.store_info()
        await self.api(ctx, "POST", f"/api/v1/stores/{s['id']}/reseller/payments/{pid}/review", json={"approve": flag == "1", "note": None if flag == "1" else "رد از طریق ربات"})
        await self.send(ctx.chat_id, "پرداخت تأیید شد ✅" if flag == "1" else "پرداخت رد شد ❌")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    raw = os.getenv("MELORIN_RESELLER_BOTS_JSON", "").strip()
    if raw:
        try:
            configs = json.loads(raw)
            if not isinstance(configs, list) or not configs:
                raise ValueError
            bots = []
            for i, cfg in enumerate(configs):
                if not isinstance(cfg, dict) or not cfg.get("token") or not cfg.get("store_slug"):
                    raise ValueError("each bot needs token and store_slug")
                slug = str(cfg["store_slug"])
                safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in slug)[:60]
                bots.append(ResellerTelegramRunner(token=str(cfg["token"]), slug=slug, state_suffix=f"{i}-{safe}"))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"MELORIN_RESELLER_BOTS_JSON is invalid: {exc}") from exc
        async def run_all():
            await asyncio.gather(*(bot.run() for bot in bots))

        asyncio.run(run_all())
    else:
        asyncio.run(ResellerTelegramRunner().run())
