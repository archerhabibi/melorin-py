"""Hosting: Core-driven supervisor (one isolated runner per store bot), static development modes and the heartbeat file."""

import asyncio
import json
import os
import time
from pathlib import Path

import httpx

from tgreseller.bot import BotRevoked, ResellerTelegramRunner, log

HEARTBEAT_SECONDS = 15


async def heartbeat_loop(path: str | None) -> None:
    """Touch a file so the container healthcheck can tell the process is alive and not stuck."""
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    while True:
        target.write_text(str(int(time.time())))
        await asyncio.sleep(HEARTBEAT_SECONDS)


class Slot:
    def __init__(self, cfg: dict, runner: ResellerTelegramRunner, task: asyncio.Task):
        self.cfg, self.runner, self.task = cfg, runner, task
        self.revoked = False  # token refused by Telegram: wait for a different token instead of retrying


class Supervisor:
    """Keeps exactly the bots Core wants running, one isolated runner per reseller store."""

    def __init__(self, *, core: str | None = None, secret: str | None = None, client: httpx.AsyncClient | None = None, make_runner=None):
        self.core = (core or os.environ["MELORIN_CORE_URL"]).rstrip("/")
        self.secret = secret or os.environ.get("MELORIN_RESELLER_BOT_SECRET") or os.environ["MELORIN_BOT_SERVICE_SECRET"]
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
        self.make_runner = make_runner or (lambda cfg: ResellerTelegramRunner(token=cfg["token"], slug=cfg["slug"], state_suffix=str(cfg["store_id"])))
        self.slots: dict[str, Slot] = {}
        self.poll_seconds = 30

    def _headers(self) -> dict:
        return {"X-Bot-Secret": self.secret, "Accept": "application/json"}

    async def fetch(self) -> list[dict] | None:
        try:
            r = await self.client.get(f"{self.core}/api/v1/internal/reseller-bots", headers=self._headers())
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError):
            log.warning("could not read the reseller bot list from Core; keeping the running bots", exc_info=True)
            return None
        self.poll_seconds = max(10, min(120, int(data.get("poll_seconds") or 30)))
        return data.get("bots") or []

    async def report(self, store_id: str, state: str, detail: str | None, fingerprint: str) -> None:
        try:
            await self.client.post(f"{self.core}/api/v1/internal/reseller-bots/{store_id}/status", headers=self._headers(),
                                   json={"state": state, "detail": detail, "fingerprint": fingerprint})
        except httpx.HTTPError:
            log.warning("could not report bot status for %s", store_id)

    async def _stop(self, key: str) -> None:
        slot = self.slots.pop(key, None)
        if slot is None:
            return
        slot.task.cancel()
        await asyncio.gather(slot.task, return_exceptions=True)
        log.info("stopped reseller bot of store %s", slot.cfg.get("slug"))

    async def sync(self) -> None:
        wanted = await self.fetch()
        if wanted is None:
            return
        by_id = {str(b["store_id"]): b for b in wanted}
        for key in [k for k in self.slots if k not in by_id]:
            await self._stop(key)  # suspended, switched off, or token removed
        for key, cfg in by_id.items():
            slot = self.slots.get(key)
            if slot and slot.cfg["fingerprint"] != cfg["fingerprint"]:
                await self._stop(key)  # token (or slug) changed: restart on the new one
                slot = None
            if slot and slot.task.done() and not slot.revoked:
                exc = None if slot.task.cancelled() else slot.task.exception()
                if isinstance(exc, BotRevoked):
                    slot.revoked = True
                else:
                    log.warning("reseller bot %s stopped unexpectedly; restarting", cfg["slug"])
                    await self._stop(key)
                    slot = None
            if slot is None:
                try:
                    runner = self.make_runner(cfg)
                except Exception:  # noqa: BLE001 - one broken store must never take the others down
                    log.exception("could not start reseller bot of %s", cfg.get("slug"))
                    continue
                self.slots[key] = Slot(cfg, runner, asyncio.create_task(runner.run(), name=f"reseller-{cfg['slug']}"))
                log.info("started reseller bot of store %s (@%s)", cfg["slug"], cfg.get("bot_username"))
        for key, slot in list(self.slots.items()):
            if slot.task.done() and not slot.revoked and isinstance(None if slot.task.cancelled() else slot.task.exception(), BotRevoked):
                slot.revoked = True
            state, detail = ("error", slot.runner.health_detail) if slot.revoked else (slot.runner.health, slot.runner.health_detail)
            await self.report(key, state, detail, slot.cfg["fingerprint"])

    async def run(self) -> None:
        try:
            while True:
                await self.sync()
                await asyncio.sleep(self.poll_seconds)
        finally:
            for key in list(self.slots):
                await self._stop(key)
            await self.client.aclose()


def _static_bots() -> list[ResellerTelegramRunner] | None:
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
            return bots
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"MELORIN_RESELLER_BOTS_JSON is invalid: {exc}") from exc
    if os.getenv("MELORIN_TELEGRAM_RESELLER_TOKEN") and os.getenv("MELORIN_STORE_SLUG"):
        return [ResellerTelegramRunner()]
    return None
