"""Static guard for the audit P0 operations baseline: restart policies, alert delivery, CI-gated deploy, rollback script."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []

compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
for name, svc in compose["services"].items():
    if svc.get("restart") not in {"unless-stopped", "always"}:
        errors.append(f"docker-compose.yml: service '{name}' has no restart policy (W2)")
if "alertmanager" not in compose["services"]:
    errors.append("docker-compose.yml: no alertmanager service (W5)")
prom = yaml.safe_load((ROOT / "infra/prometheus.yml").read_text())
if not prom.get("alerting", {}).get("alertmanagers"):
    errors.append("infra/prometheus.yml: no alerting.alertmanagers block (W5)")

wf = yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text())
triggers = wf.get(True) or wf.get("on") or {}
if "push" in triggers:
    errors.append("deploy.yml: must not trigger on push; deploy only after CI succeeded (W1)")
if "workflow_run" not in triggers:
    errors.append("deploy.yml: missing workflow_run trigger on CI (W1)")
job_if = str(wf["jobs"]["deploy"].get("if", ""))
if "conclusion == 'success'" not in job_if:
    errors.append("deploy.yml: deploy job must require workflow_run.conclusion == 'success' (W1)")
if "deploy.sh" not in (ROOT / ".github/workflows/deploy.yml").read_text():
    errors.append("deploy.yml: must call scripts/deploy.sh (rollback logic) (W3)")

deploy = (ROOT / "scripts/deploy.sh").read_text()
for needle in ("rollback()", "backup_secure.sh", "alembic upgrade head", "health/ready", "flock"):
    if needle not in deploy:
        errors.append(f"scripts/deploy.sh: missing '{needle}'")

ci = (ROOT / ".github/workflows/ci.yml").read_text()
if "test_deploy.sh" not in ci or "check_ops_p0.py" not in ci:
    errors.append("ci.yml: test_deploy.sh and check_ops_p0.py must run in CI")

if errors:
    raise SystemExit("ops baseline violations:\n - " + "\n - ".join(errors))
print("Ops P0 baseline OK: restart policies, Alertmanager, CI-gated deploy with rollback")
