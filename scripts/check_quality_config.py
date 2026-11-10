"""Static guard that the declared quality policy is present and consistent."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
pyproject = (ROOT / "apps/api/pyproject.toml").read_text()
gate = (ROOT / "scripts/run_quality_gate.sh").read_text()
ci = (ROOT / ".github/workflows/ci.yml").read_text()

# Must mirror [tool.ruff.lint] select in apps/api/pyproject.toml. Audit T30/T41 widened it with DTZ (naive datetimes),
# B (bugbear), ASYNC and S (security); keep both places in sync when it changes again.
required = ('"E4"', '"E9"', '"F"', '"DTZ"', '"B"', '"ASYNC"', '"S"')
missing = [rule for rule in required if rule not in pyproject]
if missing:
    raise SystemExit(f"quality policy missing rules: {missing}")
# Phase 2 (code hygiene): unused imports (F401) are enforced; do not silence them again in the ruff ignore list.
ignore_line = next((line for line in pyproject.splitlines() if line.startswith("ignore =")), "")
if '"F401"' in ignore_line:
    raise SystemExit("ruff must not ignore F401 (unused imports)")
for text in (gate, ci):
    if "ruff check" not in text or "ruff format --check" not in text:
        raise SystemExit("quality gate is missing ruff check or format check")
# M6.11: the guard scripts themselves must stay wired into the gate, CI and the Makefile.
makefile = (ROOT / "Makefile").read_text()
for name in ("check_g001_g010.py", "check_quality_config.py", "gen_docs.py", "gen_api_client.py"):
    for label, text in (("run_quality_gate.sh", gate), ("ci.yml", ci), ("Makefile", makefile)):
        if name not in text:
            raise SystemExit(f"guard {name} is not wired into {label}")
# Phase 6: frontend lint/format/budget must stay wired into CI, and each web app must ship its configs.
for needle in ("npm run lint", "npm run format:check", "check_bundle_budget.py"):
    if needle not in ci:
        raise SystemExit(f"CI is missing the frontend step: {needle}")
for web in ("apps/store-web", "apps/admin-web"):
    for cfg in ("eslint.config.js", ".prettierrc.json"):
        if not (ROOT / web / cfg).exists():
            raise SystemExit(f"{web}/{cfg} is missing")
# T-R3: both Telegram bot suites and the alembic format check must run in the local gate and in CI, not in only one of them.
for label, text in (("run_quality_gate.sh", gate), ("ci.yml", ci)):
    for needle in ("../telegram-main/tests", "../telegram-reseller/tests"):
        if needle not in text:
            raise SystemExit(f"{label} does not run the bot suite {needle}")
    if "apps/api/alembic" not in text and "tests alembic" not in text:
        raise SystemExit(f"{label} does not format-check alembic migrations")
print("Quality configuration is explicit and wired into local gate and CI")
