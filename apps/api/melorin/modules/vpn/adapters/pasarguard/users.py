"""PasarGuard account lifecycle (user create/read/modify/delete/reset/rotate) plus per-user usage and devices."""

import datetime as dt
from urllib.parse import quote

from melorin.modules.vpn.adapters.base import AccountSpec, ErrorKind, PanelAccount, PanelError
from melorin.modules.vpn.adapters.pasarguard.core import as_rows, iso_expire, parse_expire

USAGE_PERIODS = ("minute", "hour", "day", "month")  # PasarGuard ``Period`` enum
_STATUS = {"active": "active", "disabled": "disabled", "expired": "expired", "limited": "limited", "on_hold": "active"}


def build_create_payload(spec: AccountSpec, cfg: dict) -> dict:
    template_id = cfg.get("user_template_id")
    if template_id is not None:
        try:
            template_id = int(template_id)
        except (TypeError, ValueError) as exc:
            raise PanelError(ErrorKind.PERMANENT, "pasarguard: config.user_template_id must be an integer") from exc
        if template_id <= 0:
            raise PanelError(ErrorKind.PERMANENT, "pasarguard: config.user_template_id must be positive")
        body = {"user_template_id": template_id, "username": spec.username}
        if spec.note:
            body["note"] = spec.note[:500]
        return body
    group_ids = [int(g) for g in (cfg.get("group_ids") or [])]
    if not group_ids:
        raise PanelError(ErrorKind.PERMANENT, "pasarguard: config.group_ids is required")
    body: dict = {
        "username": spec.username,
        "status": "active",
        "group_ids": group_ids,
        "proxy_settings": cfg.get("proxy_settings") or {},
        "data_limit": int(spec.traffic_bytes or 0),
        "expire": iso_expire(spec.expire_at),
    }
    if spec.max_devices and int(spec.max_devices) > 0:
        body["hwid_limit"] = int(spec.max_devices)
    if spec.note:
        body["note"] = spec.note[:500]
    if cfg.get("data_limit_reset_strategy"):
        body["data_limit_reset_strategy"] = cfg["data_limit_reset_strategy"]
    return body


def build_modify_payload(
    *, expire_at: dt.datetime | None = None, traffic_bytes: int | None = None, status: str | None = None, set_expire: bool = False
) -> dict:
    body: dict = {}
    if set_expire:
        body["expire"] = iso_expire(expire_at)
    if traffic_bytes is not None:
        body["data_limit"] = int(traffic_bytes)
    if status:
        body["status"] = status
    return body


class UsersMixin:
    # ------------------------------------------------------------------ paths
    @staticmethod
    def _q(username: str) -> str:
        return quote(username, safe="")

    def _read_path(self, username: str) -> str:
        return f"/api/user/{self._q(username)}" if self.legacy else f"/api/user/by-username/{self._q(username)}"

    def _write_path(self, d: dict, suffix: str = "") -> str:
        if self.legacy or d.get("id") is None:
            return f"/api/user/{self._q(d['username'])}{suffix}"
        return f"/api/user/by-id/{int(d['id'])}{suffix}"

    async def _get_raw(self, username: str) -> dict | None:
        d = await self._req("GET", self._read_path(username), ok404=True)
        return d or None

    async def _require(self, username: str) -> dict:
        d = await self._get_raw(username)
        if not d:
            raise PanelError(ErrorKind.PERMANENT, f"pasarguard: user {username} not found")
        return d

    # ------------------------------------------------------------------ mapping
    def _to_account(self, d: dict) -> PanelAccount:
        sub = d.get("subscription_url")
        if sub and sub.startswith("/"):
            sub = (self.cfg.get("sub_base_url") or self.base).rstrip("/") + sub
        links = d.get("links") or []
        raw_status = str(d.get("status") or "")
        lifetime = d.get("lifetime_used_traffic")
        owner = d.get("admin")
        return PanelAccount(
            ref=str(d.get("id") if d.get("id") is not None else d["username"]),
            username=d["username"],
            status=self.normalize_status(str(d.get("status") or "")),
            expire_at=parse_expire(d.get("expire")),
            traffic_limit_bytes=int(d.get("data_limit") or 0),
            traffic_used_bytes=int(d.get("used_traffic") or 0),
            subscription_url=sub,
            links=list(links) if isinstance(links, list) else [],
            remote_status=raw_status or None,
            online_at=parse_expire(d.get("online_at")),
            lifetime_used_bytes=int(lifetime) if isinstance(lifetime, int | float) and not isinstance(lifetime, bool) else None,
            owner=str(owner.get("username")) if isinstance(owner, dict) and owner.get("username") else None,
            next_plan=self._next_plan_of(d),
        )

    @staticmethod
    def _next_plan_of(d: dict) -> dict | None:
        plan = d.get("next_plan")
        if not isinstance(plan, dict) or not any(v not in (None, 0, False) for v in plan.values()):
            return None
        return {k: plan.get(k) for k in ("user_template_id", "data_limit", "expire", "add_remaining_traffic") if k in plan}

    # ------------------------------------------------------------------ account listing (AccountListing, PG-04)
    async def list_accounts(self, *, offset: int = 0, limit: int = 100) -> tuple[list[PanelAccount], int | None]:
        """One page of ``GET /api/users`` (``load_sub=false``: no subscription rendering, so a page stays cheap)."""
        data = await self._req("GET", "/api/users", params={"offset": int(offset), "limit": int(limit), "load_sub": "false"})
        rows = [r for r in as_rows(data, "users", "items") if isinstance(r, dict) and r.get("username")]
        total = data.get("total") if isinstance(data, dict) else None
        return [self._to_account(r) for r in rows], total if isinstance(total, int) else None

    def _template_mode(self) -> bool:
        return self.cfg.get("user_template_id") is not None

    def _product_limits(self) -> bool:
        """A template carries its own volume/time. By default the PACKAGE wins (``limits_from=product``), so one template can
        serve every plan; ``limits_from=template`` keeps whatever the template says."""
        return self._template_mode() and self.cfg.get("limits_from", "product") == "product"

    @staticmethod
    def _limits_match(d: dict, spec: AccountSpec) -> bool:
        want_exp = parse_expire(iso_expire(spec.expire_at))
        have_exp = parse_expire(d.get("expire"))
        same_exp = (want_exp is None and have_exp is None) or (
            want_exp is not None and have_exp is not None and abs((want_exp - have_exp).total_seconds()) < 2
        )
        return same_exp and int(d.get("data_limit") or 0) == int(spec.traffic_bytes or 0)

    async def _apply_product_limits(self, d: dict, spec: AccountSpec) -> dict:
        """Step 2 of template creation: overwrite the template's volume/time with the package's (absolute values: safe to repeat)."""
        if self._limits_match(d, spec):
            return d
        out = await self._req(
            "PUT",
            self._write_path(d),
            json=build_modify_payload(expire_at=spec.expire_at, traffic_bytes=spec.traffic_bytes, set_expire=True),
        )
        return out if isinstance(out, dict) and out.get("username") else await self._require(spec.username)

    @staticmethod
    def _owner_of(d: dict) -> str | None:
        admin = d.get("admin")
        return admin.get("username") if isinstance(admin, dict) else None

    async def _ensure_owner(self, d: dict, owner: str | None) -> dict:
        """Make ``owner`` (a panel admin) the owner of user ``d``. Idempotent; a failure is TRANSIENT so the order retries and the
        account is never left under the wrong admin silently."""
        if not owner or self._owner_of(d) == owner:
            return d
        try:
            out = await self._req(
                "PUT",
                self._write_path(d, "/set_owner"),
                params={"admin_username": owner},
            )
        except PanelError as e:
            raise PanelError(ErrorKind.TRANSIENT, f"pasarguard: set owner {owner}: {e.message}") from e
        return out if isinstance(out, dict) and out.get("username") else await self._require(d["username"])

    async def create_account(self, spec: AccountSpec) -> PanelAccount:
        existing = await self._get_raw(spec.username)
        if existing:  # idempotent retry after an UNKNOWN outcome
            if self._product_limits():  # the previous attempt may have died between create and the limits step
                existing = await self._apply_product_limits(existing, spec)
            return self._to_account(await self._ensure_owner(existing, spec.owner))
        endpoint = "/api/user/from_template" if self._template_mode() else "/api/user"
        d = await self._req("POST", endpoint, json=build_create_payload(spec, self.cfg), ok409=True)
        if d.get("__conflict__"):
            d = await self._require(spec.username)
        elif not d.get("username"):
            d = await self._require(spec.username)
        if self._product_limits():
            d = await self._apply_product_limits(d, spec)
        d = await self._ensure_owner(d, spec.owner)
        return self._to_account(d)

    async def get_account(self, username: str) -> PanelAccount | None:
        d = await self._get_raw(username)
        return self._to_account(d) if d else None

    async def suspend_account(self, username: str) -> None:
        d = await self._require(username)
        await self._req("PUT", self._write_path(d), json=build_modify_payload(status="disabled"))

    async def resume_account(self, username: str) -> None:
        d = await self._require(username)
        await self._req("PUT", self._write_path(d), json=build_modify_payload(status="active"))

    async def extend_account(self, username: str, *, expire_at: dt.datetime | None, traffic_bytes: int) -> PanelAccount:
        d = await self._require(username)
        out = await self._req(
            "PUT",
            self._write_path(d),
            json=build_modify_payload(expire_at=expire_at, traffic_bytes=traffic_bytes, status="active", set_expire=True),
        )
        return self._to_account(out if out.get("username") else await self._require(username))

    async def revoke_account(self, username: str) -> None:
        d = await self._get_raw(username)
        if not d:
            return  # already gone: idempotent
        await self._req("DELETE", self._write_path(d), ok404=True)

    async def reset_traffic(self, username: str) -> PanelAccount:
        d = await self._require(username)
        out = await self._req("POST", self._write_path(d, "/reset"))
        return self._to_account(out if out.get("username") else await self._require(username))

    async def rotate_subscription(self, username: str) -> PanelAccount:
        d = await self._require(username)
        out = await self._req("POST", self._write_path(d, "/revoke_sub"))
        return self._to_account(out if out.get("username") else await self._require(username))

    def normalize_status(self, raw: str) -> str:
        return _STATUS.get(raw, "unknown")

    # ------------------------------------------------------------------ next plan / template move (NextPlanOps, PG-09)
    async def _modify(self, username: str, body: dict) -> PanelAccount:
        d = await self._require(username)
        out = await self._req("PUT", self._write_path(d), json=body)
        return self._to_account(out if isinstance(out, dict) and out.get("username") else await self._require(username))

    async def set_next_plan(self, username: str, *, template_id: int, add_remaining_traffic: bool = False) -> PanelAccount:
        """Queue ``template_id`` as the package the panel switches to when the current one ends. Absolute value: safe to repeat."""
        if isinstance(template_id, bool) or int(template_id) <= 0:
            raise PanelError(ErrorKind.PERMANENT, "pasarguard: next plan needs a positive template id")
        plan = {"user_template_id": int(template_id), "add_remaining_traffic": bool(add_remaining_traffic)}
        return await self._modify(username, {"next_plan": plan})

    async def clear_next_plan(self, username: str) -> PanelAccount:
        return await self._modify(username, {"next_plan": None})

    async def activate_next_plan(self, username: str) -> PanelAccount:
        """Start the queued package now (the panel does it by itself when the current one ends)."""
        d = await self._require(username)
        out = await self._req("POST", self._write_path(d, "/active_next"))
        return self._to_account(out if isinstance(out, dict) and out.get("username") else await self._require(username))

    async def apply_template(self, username: str, template_id: int) -> PanelAccount:
        """Move an existing account to a template's groups, volume and time (plan change)."""
        if self.legacy:
            raise PanelError(ErrorKind.PERMANENT, "pasarguard: template change needs the current API style")
        d = await self._require(username)
        out = await self._req("PUT", f"/api/user/from_template/by-id/{int(d['id'])}", json={"user_template_id": int(template_id)})
        return self._to_account(out if isinstance(out, dict) and out.get("username") else await self._require(username))

    # ------------------------------------------------------------------ usage (UsageOps)
    async def get_usage(
        self, username: str, *, start: dt.datetime | None = None, end: dt.datetime | None = None, period: str = "day"
    ) -> list[dict]:
        """Usage history of one account: ``[{"node_id"?, "total", ...}]`` rows as the panel returns them (read-only)."""
        if period not in USAGE_PERIODS:
            raise PanelError(ErrorKind.PERMANENT, f"pasarguard: usage period must be one of {', '.join(USAGE_PERIODS)}")
        d = await self._require(username)
        params: dict = {"period": period}
        if start:
            params["start"] = iso_expire(start)
        if end:
            params["end"] = iso_expire(end)
        return as_rows(await self._req("GET", self._write_path(d, "/usage"), params=params), "stats", "usages", "items")

    # ------------------------------------------------------------------ devices (DeviceOps)
    @staticmethod
    def _device_base(d: dict) -> str:
        if d.get("id") is None:
            raise PanelError(ErrorKind.PERMANENT, "pasarguard: device operations need the panel user id")
        return f"/api/user/{int(d['id'])}/hwids"

    async def list_devices(self, username: str) -> list[dict]:
        d = await self._require(username)
        return as_rows(await self._req("GET", self._device_base(d)), "hwids", "devices", "items")

    async def delete_device(self, username: str, hwid: str) -> None:
        """Forget one device. Idempotent: a device that is already gone is not an error."""
        if not str(hwid or "").strip():
            raise PanelError(ErrorKind.PERMANENT, "pasarguard: hwid is required")
        d = await self._require(username)
        await self._req("DELETE", f"{self._device_base(d)}/{self._q(str(hwid))}", ok404=True)

    async def reset_devices(self, username: str) -> None:
        d = await self._require(username)
        await self._req("POST", f"{self._device_base(d)}/reset")
