"""Static guard for the operations baseline: restart policies, alert delivery, CI-gated deploy, rollback script (audit P0)
and the Phase 5 release hardening (hash-locked requirements, runtime image without dev/build tooling).

Importable: the check helpers have no side effects; the checks run only when executed as a script.
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

DEV_ONLY_PACKAGES = {"pytest", "pytest-asyncio", "pytest-cov", "ruff", "import-linter", "coverage"}
LOCK_FILES = [
    "apps/api/requirements.txt",
    "apps/api/requirements-dev.txt",
    "apps/telegram-main/requirements.txt",
    "apps/telegram-reseller/requirements.txt",
]


def lock_problems(path: Path) -> list[str]:
    """Every pinned requirement in a pip-compile lock must carry at least one sha256 hash and be an exact ==pin."""
    problems: list[str] = []
    logical = re.sub(r"\\\n\s*", " ", path.read_text())  # join backslash continuations
    seen = 0
    for line in logical.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        seen += 1
        if not re.match(r"^[A-Za-z0-9_.-]+(\[[^\]]*\])?==[^\s;]+", line):
            problems.append(f"{path.name}: not an exact pin: {line[:60]}")
        elif "--hash=sha256:" not in line:
            problems.append(f"{path.name}: no hash for {line.split()[0]}")
    if seen == 0:
        problems.append(f"{path.name}: no requirements found")
    return problems


def runtime_lock_dev_leaks(path: Path) -> list[str]:
    names = {m.group(1).lower().replace("_", "-") for m in re.finditer(r"(?m)^([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==", path.read_text())}
    return sorted(names & DEV_ONLY_PACKAGES)


def main() -> int:
    errors: list[str] = []
    run_checks(errors)
    if errors:
        print("ops baseline violations:\n - " + "\n - ".join(errors), file=sys.stderr)
        return 1
    print("Ops baseline OK: restart policies, Alertmanager, CI-gated deploy with rollback, hash-locked requirements")
    return 0


def run_checks(errors: list[str]) -> None:

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
    for needle in ("test_deploy.sh", "test_restore_drill.sh", "check_ops_p0.py"):
        if needle not in ci:
            errors.append(f"ci.yml: {needle} must run in CI")

    for rel in LOCK_FILES:
        path = ROOT / rel
        if not path.is_file():
            errors.append(f"{rel}: lock file is missing (scripts/lock_requirements.sh)")
            continue
        errors.extend(lock_problems(path))
    for rel in ("apps/api/requirements.txt", "apps/telegram-main/requirements.txt", "apps/telegram-reseller/requirements.txt"):
        leaked = runtime_lock_dev_leaks(ROOT / rel) if (ROOT / rel).is_file() else []
        if leaked:
            errors.append(f"{rel}: runtime lock must not contain dev tooling: {', '.join(leaked)}")
    for rel in ("apps/api/Dockerfile", "apps/telegram-main/Dockerfile", "apps/telegram-reseller/Dockerfile"):
        if "--require-hashes" not in (ROOT / rel).read_text():
            errors.append(f"{rel}: pip install must use --require-hashes (W17)")


if __name__ == "__main__":
    raise SystemExit(main())
