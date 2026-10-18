# Runtime evidence collector (M7.3)

`scripts/runtime_evidence.py` gathers the evidence that unit tests cannot provide and that
[`RELEASE-EVIDENCE-MATRIX.md`](RELEASE-EVIDENCE-MATRIX.md) requires before any "Runtime-tested" cell may turn green.

**It is fail-closed.** A check without its prerequisites is `skipped` (with the reason), never `passed`; any skipped
check makes the exit code non-zero (3) unless `--allow-skip` is given; a failure exits 1. Secrets are masked in
`summary.json`, `summary.md` and logs. Nothing in the repository claims these checks have already run.

```bash
python scripts/runtime_evidence.py --list
python scripts/runtime_evidence.py --only telegram_main,zarinpal_sandbox
python scripts/runtime_evidence.py --allow-mutation        # everything that is configured
make evidence                                                # same, via Makefile
```

The bundle is written to `var/evidence/m73-<UTC timestamp>/` (`summary.json`, `summary.md`, build/validate logs).
Attach it to the release record and flip only the matrix cells whose checks are `passed`.

| Check | Proves | Needs |
|---|---|---|
| `telegram_main` | Main bot token is valid (`getMe`) and no webhook blocks long polling | `MELORIN_TELEGRAM_TOKEN` |
| `telegram_reseller` | Same for a reseller bot | `MELORIN_TELEGRAM_RESELLER_BOT_TOKEN` |
| `zarinpal_sandbox` | `request.json` returns a sandbox StartPay URL; cancelled, unpaid and forged callbacks never verify | `MELORIN_ZARINPAL_SANDBOX_MERCHANT` (any sandbox merchant UUID) |
| `panel_roundtrip` | health, create, read, extend, suspend/resume, revoke and "gone" on each real panel (Sanaei, PasarGuard) | `MELORIN_EVIDENCE_PANELS` (JSON file path) and `--allow-mutation` |
| `docker_build` | `docker compose config` and all three image builds | docker CLI/daemon |
| `caddy_config` | `infra/Caddyfile` validates (including the on-demand TLS block) | `caddy` or docker |
| `tls_ask_gate` | `/api/v1/tls/ask` answers 200 for an active reseller domain and 404 for everything else | `MELORIN_EVIDENCE_API_URL`, `MELORIN_EVIDENCE_RESELLER_DOMAIN` |
| `prometheus_rules` | `infra/alerts.yml` passes `promtool check rules` | `promtool` or docker |
| `prometheus_scrape` | Prometheus scrapes `melorin-api` (`up == 1`) and loaded the `melorin-core` rule group | `MELORIN_PROMETHEUS_URL` |
| `alert_delivery` | A synthetic alert pushed to Alertmanager reaches the receiver | `MELORIN_ALERTMANAGER_URL`, `MELORIN_ALERT_RECEIVER_PROBE_URL` |

`MELORIN_EVIDENCE_PANELS` example (credentials stay in the file, never in the bundle):

```json
[{"name": "tehran-1", "kind": "pasarguard", "base_url": "https://panel.example.com",
  "credentials": {"username": "admin", "password": "..."}, "config": {"group_ids": [1]}}]
```

Not automatable here and therefore recorded by hand: a real card payment in the Zarinpal sandbox (needs a browser),
the first real certificate issued for a reseller domain (needs public DNS), and Telegram end-to-end conversations.
