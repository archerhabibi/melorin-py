"""Static guard for the operations baseline: restart policies, alert delivery, CI-gated deploy, rollback script (audit P0)
and the Phase 5 release hardening (hash-locked requirements, runtime image without dev/build tooling).

Importable: the check helpers have no side effects; the checks run only when executed as a script.
"""
import importlib.util
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

DEV_ONLY_PACKAGES = {"pytest", "pytest-asyncio", "pytest-cov", "ruff", "import-linter", "coverage"}
MEMORY_BUDGET_MIB = 3584  # sum of every mem_limit in docker-compose.yml; README recommends 4 GB RAM for it
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


def api_dockerfile_problems(text: str) -> list[str]:
    """The API image is multi-stage and its final (runtime) stage carries no fetch/build tooling (W17)."""
    problems: list[str] = []
    stages = re.split(r"(?im)^FROM\s+", text)[1:]
    if len(stages) < 3:
        return ["apps/api/Dockerfile: expected a multi-stage build (key fetch, venv, runtime)"]
    runtime = stages[-1]
    logical = re.sub(r"\\\n\s*", " ", runtime)  # join RUN continuations so a package list split over lines is still seen
    for line in logical.splitlines():
        if re.search(r"apt-get\s+install", line):
            for tool in ("curl", "gnupg", "build-essential", "gcc"):
                if re.search(rf"(?<![\w-]){tool}(?![\w-])", line):
                    problems.append(f"apps/api/Dockerfile: runtime stage installs '{tool}'; keep it in a throw-away stage")
    if "pip install" in runtime:
        problems.append("apps/api/Dockerfile: runtime stage must copy the venv, not run pip install")
    if "USER appuser" not in runtime:
        problems.append("apps/api/Dockerfile: runtime stage must drop to a non-root user")
    return problems


def image_pin_problems() -> list[str]:
    """Images are pinned by digest as a set: once one is, all must be. Unpinned everywhere only warns (pin needs registry access)."""
    spec = importlib.util.spec_from_file_location("pin_images", ROOT / "scripts/pin_images.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    refs = module.find_refs(ROOT)
    pinned = [r for r in refs if r.pinned]
    unpinned = [r for r in refs if not r.pinned]
    if pinned and unpinned:
        return [f"{r.file.relative_to(ROOT)}:{r.line}: image '{r.ref}' is not pinned by digest (others are)" for r in unpinned]
    if unpinned:
        print(f"note: {len(unpinned)} image references are not pinned by digest yet - run the 'Pin images' workflow", file=sys.stderr)
    return []


def _mib(value: object) -> int | None:
    m = re.fullmatch(r"(\d+)\s*([kmg])b?", str(value).strip().lower())
    if not m:
        return None
    return int(int(m.group(1)) * {"k": 1 / 1024, "m": 1, "g": 1024}[m.group(2)])


def memory_problems(compose: dict) -> list[str]:
    """Every service is capped, the caps fit the documented budget, and Redis stops itself before its container cap (W6)."""
    problems: list[str] = []
    total = 0
    services = compose["services"]
    for name, svc in services.items():
        cap = _mib(svc.get("mem_limit", ""))
        if cap is None:
            problems.append(f"docker-compose.yml: service '{name}' has no mem_limit (W6)")
        else:
            total += cap
    if total > MEMORY_BUDGET_MIB:
        problems.append(f"docker-compose.yml: mem_limit total {total} MiB exceeds the {MEMORY_BUDGET_MIB} MiB budget (update README + MEMORY_BUDGET_MIB together)")
    cmd = services.get("redis", {}).get("command", "")
    cmd = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
    m = re.search(r"--maxmemory\s+(\d+\s*[kmg]b?)", cmd, re.IGNORECASE)
    redis_cap = _mib(services.get("redis", {}).get("mem_limit", ""))
    if not m:
        problems.append("docker-compose.yml: redis needs --maxmemory below its container cap")
    elif redis_cap is not None and (_mib(m.group(1)) or 0) >= redis_cap:
        problems.append("docker-compose.yml: redis --maxmemory must be lower than its mem_limit")
    if "noeviction" not in cmd:
        problems.append("docker-compose.yml: redis must use --maxmemory-policy noeviction (queue and rate-limit keys are never dropped silently)")
    return problems


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
    # The CI gate lives in the first job ("prepare"); build/deploy jobs hang off it through needs, so they can never run without it.
    jobs = wf["jobs"]
    if "conclusion == 'success'" not in str(jobs["prepare"].get("if", "")):
        errors.append("deploy.yml: prepare job must require workflow_run.conclusion == 'success' (W1)")
    if "prepare" not in (jobs["deploy"].get("needs") or []):
        errors.append("deploy.yml: deploy job must depend on the CI-gated prepare job (W1)")
    if "needs.prepare.result == 'success'" not in str(jobs["deploy"].get("if", "")):
        errors.append("deploy.yml: deploy job must require the prepare job to have succeeded (W1)")
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
    errors.extend(memory_problems(compose))
    for readme in ("README.md", "README.fa.md"):
        if not re.search(r"\b4 GB|۴ گیگ", (ROOT / readme).read_text()):
            errors.append(f"{readme}: the recommended RAM must match the {MEMORY_BUDGET_MIB} MiB memory budget (4 GB)")
    errors.extend(api_dockerfile_problems((ROOT / "apps/api/Dockerfile").read_text()))
    errors.extend(image_pin_problems())


if __name__ == "__main__":
    raise SystemExit(main())
