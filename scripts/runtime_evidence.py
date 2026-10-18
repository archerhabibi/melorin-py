#!/usr/bin/env python3
"""M7.3 - fail-closed runtime evidence collector.

Collects the runtime evidence that unit tests cannot provide and that ``docs/RELEASE-EVIDENCE-MATRIX.md`` requires:
Telegram bots, the Zarinpal sandbox, real VPN panels, Docker image builds, Caddy configuration and the on-demand TLS
gate, Prometheus scrape/rules and Alertmanager delivery.

Rules this script never breaks:
* A check whose prerequisites are missing is reported as ``skipped`` with the reason - never as ``passed``.
* ``skipped`` makes the exit code non-zero unless ``--allow-skip`` is given, so a green run means real evidence.
* Secrets (bot tokens, panel passwords, API keys) never reach ``summary.json`` / ``summary.md`` / logs.
* Mutating checks (creating and deleting a throwaway account on a real panel) require ``--allow-mutation``.

Exit codes: 0 all selected checks passed, 1 at least one failed, 3 none failed but at least one was skipped.

Usage::

    python scripts/runtime_evidence.py --list
    MELORIN_TELEGRAM_TOKEN=... python scripts/runtime_evidence.py --only telegram_main
    python scripts/runtime_evidence.py --allow-mutation          # everything configured in the environment
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import types
import uuid
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

PASSED, FAILED, SKIPPED = "passed", "failed", "skipped"
_SECRET_NAME = re.compile(r"(TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIAL)", re.I)
_BOT_TOKEN = re.compile(r"bot\d{5,}:[A-Za-z0-9_-]{20,}")


@dataclasses.dataclass
class Result:
    name: str
    status: str
    reason: str = ""
    details: dict = dataclasses.field(default_factory=dict)
    duration_s: float = 0.0


def passed(**details) -> Result:
    return Result("", PASSED, details=details)


def failed(reason: str, **details) -> Result:
    return Result("", FAILED, reason, details)


def skipped(reason: str, **details) -> Result:
    return Result("", SKIPPED, reason, details)


class Redactor:
    """Masks every secret value found in the environment (and anything shaped like a Telegram bot token)."""

    def __init__(self, env: Mapping[str, str], extra: list[str] | None = None):
        values = {v for k, v in env.items() if _SECRET_NAME.search(k) and v and len(v) >= 6}
        values.update(v for v in (extra or []) if v and len(v) >= 6)
        self._values = sorted(values, key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for value in self._values:
            text = text.replace(value, "***")
        return _BOT_TOKEN.sub("bot***", text)

    def deep(self, obj):
        if isinstance(obj, str):
            return self(obj)
        if isinstance(obj, dict):
            return {k: self.deep(v) for k, v in obj.items()}
        if isinstance(obj, list | tuple):
            return [self.deep(v) for v in obj]
        return obj


def run_command(cmd: list[str], timeout: int = 600, cwd: Path | None = None) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd or ROOT, check=False)  # noqa: S603
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {' '.join(cmd[:3])}"
    except OSError as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout + proc.stderr)[-4000:]


def default_adapter_factory(cfg: dict):
    from melorin.modules.vpn.adapters.registry import ADAPTERS

    try:
        cls = ADAPTERS[cfg["kind"]]
    except KeyError as exc:
        raise ValueError(f"unknown panel kind {cfg.get('kind')!r}") from exc
    return cls(base_url=cfg["base_url"], credentials=cfg.get("credentials") or {}, config=cfg.get("config") or {})


@dataclasses.dataclass
class Context:
    env: Mapping[str, str]
    evidence_dir: Path
    allow_mutation: bool = False
    http: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(timeout=15, follow_redirects=False)
    run: Callable[..., tuple[int, str]] = run_command
    which: Callable[[str], str | None] = shutil.which
    adapter_factory: Callable[[dict], object] = default_adapter_factory
    sleep: Callable[[float], Awaitable] = asyncio.sleep

    def need(self, *names: str) -> str | None:
        """Return a skip reason when any variable is missing, else None."""
        missing = [n for n in names if not (self.env.get(n) or "").strip()]
        return f"missing environment: {', '.join(missing)}" if missing else None

    def first(self, *names: str) -> str:
        return next(((self.env.get(n) or "").strip() for n in names if (self.env.get(n) or "").strip()), "")


# --------------------------------------------------------------------------- Telegram


async def _telegram(ctx: Context, *token_vars: str) -> Result:
    token = ctx.first(*token_vars)
    if not token:
        return skipped(f"missing environment: {' or '.join(token_vars)}")
    async with ctx.http() as client:
        me = (await client.get(f"https://api.telegram.org/bot{token}/getMe")).json()
        hook = (await client.get(f"https://api.telegram.org/bot{token}/getWebhookInfo")).json()
    if not (me.get("ok") and (me.get("result") or {}).get("is_bot")):
        return failed("getMe did not return a bot", ok=me.get("ok"), description=me.get("description"))
    webhook_url = (hook.get("result") or {}).get("url") or ""
    if webhook_url:  # the runners use long polling (getUpdates), which Telegram refuses while a webhook is set
        return failed("a webhook is registered but the runner uses long polling (getUpdates would return 409)", webhook_url=webhook_url)
    return passed(bot_username=me["result"].get("username"), bot_id=me["result"].get("id"), webhook="none (long polling ready)")


async def check_telegram_main(ctx: Context) -> Result:
    return await _telegram(ctx, "MELORIN_TELEGRAM_TOKEN", "MELORIN_TELEGRAM_BOT_TOKEN")


async def check_telegram_reseller(ctx: Context) -> Result:
    return await _telegram(ctx, "MELORIN_TELEGRAM_RESELLER_BOT_TOKEN")


# --------------------------------------------------------------------------- Zarinpal sandbox


async def check_zarinpal_sandbox(ctx: Context) -> Result:
    if reason := ctx.need("MELORIN_ZARINPAL_SANDBOX_MERCHANT"):
        return skipped(reason)
    from melorin.modules.payments.adapters.zarinpal import ZarinpalAdapter

    adapter = ZarinpalAdapter()
    settings = {"gateway.zarinpal": {"merchant_id": ctx.env["MELORIN_ZARINPAL_SANDBOX_MERCHANT"].strip(), "sandbox": True}}
    payment = types.SimpleNamespace(id=uuid.uuid4(), amount=10_000, currency="IRT", external_ref=None, status="pending")
    intent = await adapter.create_payment_intent(payment, callback_url="https://example.invalid/cb", settings=settings)
    host = urlsplit(intent.instructions["redirect_url"]).hostname
    if host != "sandbox.zarinpal.com" or not intent.external_ref:
        return failed("sandbox request.json did not yield a sandbox StartPay URL", host=host)
    payment.external_ref = intent.external_ref
    cancelled = await adapter.verify_callback({"Authority": intent.external_ref, "Status": "NOK"}, payment, settings=settings)
    unpaid = await adapter.verify_callback({"Authority": intent.external_ref, "Status": "OK"}, payment, settings=settings)
    forged = await adapter.verify_callback({"Authority": "A" + "0" * 35, "Status": "OK"}, payment, settings=settings)
    problems = [
        label
        for label, res in (
            ("cancelled callback succeeded", cancelled),
            ("unpaid authority verified as paid", unpaid),
            ("forged authority succeeded", forged),
        )
        if res.succeeded
    ]
    details = {"authority_prefix": intent.external_ref[:6], "unpaid_verify_code": (unpaid.raw.get("verify") or {}).get("code")}
    if problems:
        return failed("; ".join(problems), **details)
    # A real money movement needs a browser payment with a sandbox card; that stays a manual, documented step.
    return passed(**details, scope="request + verify negative paths against the sandbox (no browser payment performed)")


# --------------------------------------------------------------------------- real panels


async def _roundtrip(adapter, name: str) -> dict:
    from melorin.modules.vpn.adapters.base import AccountSpec

    steps: dict[str, object] = {}
    username = f"evidence_{dt.datetime.now(dt.UTC):%Y%m%d%H%M%S}_{uuid.uuid4().hex[:4]}"
    expire = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
    created = False
    try:
        steps["health_check"] = bool(await adapter.health_check())
        if not steps["health_check"]:
            raise RuntimeError("health_check returned False")
        acc = await adapter.create_account(AccountSpec(username, expire, 1024**3, 1, "melorin runtime evidence"))
        created = True
        steps["create"] = {"status": acc.status, "has_subscription": bool(acc.subscription_url)}
        got = await adapter.get_account(username)
        steps["get"] = bool(got and got.username == username)
        await adapter.extend_account(username, expire_at=expire + dt.timedelta(days=1), traffic_bytes=2 * 1024**3)
        steps["extend"] = True
        await adapter.suspend_account(username)
        await adapter.resume_account(username)
        steps["suspend_resume"] = True
        if not steps["get"]:
            raise RuntimeError("created account could not be read back")
    finally:
        if created:
            try:
                await adapter.revoke_account(username)
                steps["revoke"] = True
                steps["gone_after_revoke"] = (await adapter.get_account(username)) is None
            except Exception as exc:  # noqa: BLE001
                steps["revoke_error"] = str(exc)[:200]
        close = getattr(adapter, "close", None)
        if close:
            result = close()
            if hasattr(result, "__await__"):
                await result
    ok = steps.get("health_check") and steps.get("get") and steps.get("extend") and steps.get("revoke") and steps.get("gone_after_revoke")
    return {"panel": name, "ok": bool(ok), "steps": steps}


async def check_panel_roundtrip(ctx: Context) -> Result:
    if reason := ctx.need("MELORIN_EVIDENCE_PANELS"):
        return skipped(reason + " (path to a JSON list of {name, kind, base_url, credentials, config})")
    if not ctx.allow_mutation:
        return skipped("creates and deletes a throwaway account on each panel; re-run with --allow-mutation")
    panels = json.loads(Path(ctx.env["MELORIN_EVIDENCE_PANELS"]).read_text())
    outcomes = []
    for cfg in panels:
        name = cfg.get("name") or cfg.get("kind", "?")
        try:
            outcomes.append(await _roundtrip(ctx.adapter_factory(cfg), name))
        except Exception as exc:  # noqa: BLE001
            outcomes.append({"panel": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]})
    details = {"panels": outcomes}
    if not outcomes or not all(o["ok"] for o in outcomes):
        return failed("one or more panels failed the create/read/extend/suspend/revoke round trip", **details)
    return passed(**details)


# --------------------------------------------------------------------------- Docker / Compose


async def check_docker_build(ctx: Context) -> Result:
    if not ctx.which("docker"):
        return skipped("docker CLI not found")
    log = ctx.evidence_dir / "docker-build.log"
    steps = [
        ("compose config", ["docker", "compose", "config", "-q"]),
        ("api image", ["docker", "build", "-f", "apps/api/Dockerfile", "-t", "melorin-evidence-api", "."]),
        ("store-web image", ["docker", "build", "-f", "apps/store-web/Dockerfile", "-t", "melorin-evidence-store-web", "."]),
        ("admin-web image", ["docker", "build", "-f", "apps/admin-web/Dockerfile", "-t", "melorin-evidence-admin-web", "."]),
    ]
    outcomes, lines = {}, []
    for label, cmd in steps:
        rc, out = ctx.run(cmd, timeout=1800)
        outcomes[label] = rc == 0
        lines.append(f"$ {' '.join(cmd)}\n[rc={rc}]\n{out}\n")
    log.write_text("\n".join(lines))
    if not all(outcomes.values()):
        return failed("docker build/config failed: " + ", ".join(k for k, v in outcomes.items() if not v), steps=outcomes, log=log.name)
    return passed(steps=outcomes, log=log.name)


# --------------------------------------------------------------------------- Caddy


async def check_caddy_config(ctx: Context) -> Result:
    caddyfile = ROOT / "infra" / "Caddyfile"
    if ctx.which("caddy"):
        rc, out = ctx.run(["caddy", "validate", "--config", str(caddyfile), "--adapter", "caddyfile"], timeout=120)
        tool = "caddy"
    elif ctx.which("docker"):
        rc, out = ctx.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{caddyfile}:/etc/caddy/Caddyfile:ro",
                "caddy:2-alpine",
                "caddy",
                "validate",
                "--config",
                "/etc/caddy/Caddyfile",
                "--adapter",
                "caddyfile",
            ],
            timeout=300,
        )
        tool = "docker caddy:2-alpine"
    else:
        return skipped("neither the caddy binary nor docker is available")
    (ctx.evidence_dir / "caddy-validate.log").write_text(out)
    return passed(tool=tool) if rc == 0 else failed("caddy validate rejected infra/Caddyfile", tool=tool, output=out[-500:])


async def check_tls_ask_gate(ctx: Context) -> Result:
    """The on-demand TLS gate: Caddy may only obtain certificates for hostnames Core confirms."""
    if reason := ctx.need("MELORIN_EVIDENCE_API_URL", "MELORIN_EVIDENCE_RESELLER_DOMAIN"):
        return skipped(reason)
    base = ctx.env["MELORIN_EVIDENCE_API_URL"].rstrip("/")
    known = ctx.env["MELORIN_EVIDENCE_RESELLER_DOMAIN"].strip().lower()
    unknown = f"unregistered-{uuid.uuid4().hex[:8]}.invalid"
    async with ctx.http() as client:
        ok = await client.get(f"{base}/api/v1/tls/ask", params={"domain": known})
        refused = await client.get(f"{base}/api/v1/tls/ask", params={"domain": unknown})
        empty = await client.get(f"{base}/api/v1/tls/ask", params={"domain": ""})
    details = {"registered_status": ok.status_code, "unregistered_status": refused.status_code, "empty_status": empty.status_code}
    if ok.status_code != 200 or refused.status_code != 404 or empty.status_code != 404:
        return failed("tls/ask must answer 200 for an active reseller domain and 404 for everything else", **details)
    return passed(**details, note="certificate issuance itself needs public DNS and is recorded manually")


# --------------------------------------------------------------------------- Prometheus / Alertmanager


async def check_prometheus_rules(ctx: Context) -> Result:
    rules = ROOT / "infra" / "alerts.yml"
    if ctx.which("promtool"):
        rc, out = ctx.run(["promtool", "check", "rules", str(rules)], timeout=120)
        tool = "promtool"
    elif ctx.which("docker"):
        cmd = [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "promtool",
            "-v",
            f"{rules}:/rules/alerts.yml:ro",
            "prom/prometheus:v2.55.1",
            "check",
            "rules",
            "/rules/alerts.yml",
        ]
        rc, out = ctx.run(cmd, timeout=300)
        tool = "docker prom/prometheus:v2.55.1"
    else:
        return skipped("neither promtool nor docker is available")
    (ctx.evidence_dir / "promtool-rules.log").write_text(out)
    return passed(tool=tool) if rc == 0 else failed("promtool rejected infra/alerts.yml", tool=tool, output=out[-500:])


async def check_prometheus_scrape(ctx: Context) -> Result:
    if reason := ctx.need("MELORIN_PROMETHEUS_URL"):
        return skipped(reason)
    base = ctx.env["MELORIN_PROMETHEUS_URL"].rstrip("/")
    async with ctx.http() as client:
        ready = await client.get(f"{base}/-/ready")
        up = (await client.get(f"{base}/api/v1/query", params={"query": 'up{job="melorin-api"}'})).json()
        rules = (await client.get(f"{base}/api/v1/rules")).json()
    samples = (up.get("data") or {}).get("result") or []
    values = [s.get("value", [0, "0"])[1] for s in samples]
    groups = [g.get("name") for g in ((rules.get("data") or {}).get("groups") or [])]
    details = {"ready": ready.status_code, "up_samples": values, "rule_groups": groups}
    if ready.status_code != 200 or not values or any(v != "1" for v in values) or "melorin-core" not in groups:
        return failed("Prometheus is not scraping melorin-api successfully or the melorin-core rules are not loaded", **details)
    return passed(**details)


async def check_alert_delivery(ctx: Context) -> Result:
    """Push a synthetic alert into Alertmanager and prove the receiver actually got it."""
    if reason := ctx.need("MELORIN_ALERTMANAGER_URL"):
        return skipped(reason)
    base = ctx.env["MELORIN_ALERTMANAGER_URL"].rstrip("/")
    marker = f"evidence-{uuid.uuid4().hex[:8]}"
    now = dt.datetime.now(dt.UTC)
    alert = [
        {
            "labels": {"alertname": "MelorinEvidenceProbe", "severity": "info", "probe": marker},
            "annotations": {"summary": "Melorin runtime evidence probe - safe to ignore"},
            "startsAt": now.isoformat(),
            "endsAt": (now + dt.timedelta(minutes=2)).isoformat(),
        }
    ]
    async with ctx.http() as client:
        post = await client.post(f"{base}/api/v2/alerts", json=alert)
        if post.status_code >= 300:
            return failed("Alertmanager refused the probe alert", status=post.status_code)
        seen = False
        for _ in range(10):
            listed = (await client.get(f"{base}/api/v2/alerts")).json()
            if any((a.get("labels") or {}).get("probe") == marker for a in listed):
                seen = True
                break
            await ctx.sleep(1)
        if not seen:
            return failed("probe alert was accepted but never became visible in Alertmanager", marker=marker)
        receiver = ctx.first("MELORIN_ALERT_RECEIVER_PROBE_URL")
        if not receiver:
            return skipped(
                "alert reached Alertmanager; set MELORIN_ALERT_RECEIVER_PROBE_URL to prove delivery to the receiver", ingested=True
            )
        delivered = False
        for _ in range(20):  # group_wait defaults to 30s
            body = (await client.get(receiver, params={"probe": marker})).json()
            if body.get("received", 0) > 0:
                delivered = True
                break
            await ctx.sleep(2)
    return passed(marker=marker, delivered_to_receiver=True) if delivered else failed("alert never reached the receiver", marker=marker)


CHECKS: dict[str, Callable[[Context], Awaitable[Result]]] = {
    "telegram_main": check_telegram_main,
    "telegram_reseller": check_telegram_reseller,
    "zarinpal_sandbox": check_zarinpal_sandbox,
    "panel_roundtrip": check_panel_roundtrip,
    "docker_build": check_docker_build,
    "caddy_config": check_caddy_config,
    "tls_ask_gate": check_tls_ask_gate,
    "prometheus_rules": check_prometheus_rules,
    "prometheus_scrape": check_prometheus_scrape,
    "alert_delivery": check_alert_delivery,
}


async def run_checks(ctx: Context, names: list[str] | None = None) -> list[Result]:
    redact = Redactor(ctx.env)
    results: list[Result] = []
    for name in names or list(CHECKS):
        started = time.monotonic()
        try:
            res = await CHECKS[name](ctx)
        except Exception as exc:  # noqa: BLE001 - a crashing check is a failed check, never a pass
            res = failed(f"{type(exc).__name__}: {exc}")
        res.name = name
        res.duration_s = round(time.monotonic() - started, 2)
        res.reason, res.details = redact(res.reason), redact.deep(res.details)
        results.append(res)
    return results


def exit_code(results: list[Result], *, allow_skip: bool = False) -> int:
    if any(r.status == FAILED for r in results):
        return 1
    if not allow_skip and any(r.status == SKIPPED for r in results):
        return 3
    return 0


def write_bundle(results: list[Result], evidence_dir: Path, *, commit: str = "unknown") -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    payload = {"collected_at": stamp, "git_commit": commit, "results": [dataclasses.asdict(r) for r in results]}
    (evidence_dir / "summary.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    lines = [f"# Melorin runtime evidence - {stamp}", f"Commit: `{commit}`", "", "| Check | Status | Reason |", "|---|---|---|"]
    lines += [f"| {r.name} | {r.status} | {r.reason.replace('|', '/')} |" for r in results]
    (evidence_dir / "summary.md").write_text("\n".join(lines) + "\n")


def _git_commit() -> str:
    rc, out = run_command(["git", "rev-parse", "HEAD"], timeout=10)
    return out.strip() if rc == 0 else "unavailable"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", help="comma-separated check names")
    parser.add_argument("--list", action="store_true", help="list available checks")
    parser.add_argument("--evidence-dir", default=os.environ.get("MELORIN_EVIDENCE_DIR"))
    parser.add_argument("--allow-mutation", action="store_true", help="permit checks that create/delete throwaway data on real systems")
    parser.add_argument("--allow-skip", action="store_true", help="do not fail the run when a check is skipped")
    args = parser.parse_args(argv)
    if args.list:
        print("\n".join(CHECKS))
        return 0
    names = [n.strip() for n in args.only.split(",")] if args.only else None
    unknown = [n for n in (names or []) if n not in CHECKS]
    if unknown:
        print(f"unknown check(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    evidence_dir = Path(args.evidence_dir or ROOT / "var" / "evidence" / f"m73-{dt.datetime.now(dt.UTC):%Y%m%dT%H%M%SZ}")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    ctx = Context(env=dict(os.environ), evidence_dir=evidence_dir, allow_mutation=args.allow_mutation)
    results = asyncio.run(run_checks(ctx, names))
    write_bundle(results, evidence_dir, commit=_git_commit())
    for r in results:
        print(f"[{r.status.upper():7}] {r.name}: {r.reason or 'ok'}")
    print(f"evidence bundle: {evidence_dir}")
    return exit_code(results, allow_skip=args.allow_skip)


if __name__ == "__main__":
    sys.exit(main())
