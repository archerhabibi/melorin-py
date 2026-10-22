"""Phase 5 (infra and release) regression guards. Static: they read the repo files, no Docker needed."""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _load_guard():
    spec = importlib.util.spec_from_file_location("check_ops_p0", ROOT / "scripts/check_ops_p0.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ops_baseline_guard_passes():
    done = subprocess.run([sys.executable, str(ROOT / "scripts/check_ops_p0.py")], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_lock_parser_flags_unhashed_and_unpinned(tmp_path):
    guard = _load_guard()
    lock = tmp_path / "requirements.txt"
    lock.write_text("good==1.0 \\\n    --hash=sha256:aa \\\n    --hash=sha256:bb\n    # via -r requirements.in\nbare==2.0\nloose>=3\n")
    problems = guard.lock_problems(lock)
    assert any("no hash for bare==2.0" in p for p in problems)
    assert any("not an exact pin" in p for p in problems)
    assert not any("good" in p for p in problems)


def test_lock_parser_rejects_empty_file(tmp_path):
    lock = tmp_path / "requirements.txt"
    lock.write_text("# nothing here\n")
    assert _load_guard().lock_problems(lock)


def test_runtime_lock_has_no_dev_tooling_but_dev_lock_does():
    guard = _load_guard()
    assert guard.runtime_lock_dev_leaks(ROOT / "apps/api/requirements.txt") == []
    assert "pytest" in guard.runtime_lock_dev_leaks(ROOT / "apps/api/requirements-dev.txt")


def test_runtime_lock_keeps_tzdata_for_zoneinfo():
    # slim images ship no /usr/share/zoneinfo; admin timeseries resolves user time zones with zoneinfo
    assert "\ntzdata==" in (ROOT / "apps/api/requirements.txt").read_text()


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_api_dockerfile_is_multi_stage_without_build_tooling_in_runtime():
    guard = _load_guard()
    text = (ROOT / "apps/api/Dockerfile").read_text()
    assert guard.api_dockerfile_problems(text) == []
    runtime = text.split("FROM base AS runtime", 1)[1]
    assert "curl" not in runtime and "gnupg" not in runtime
    assert "COPY --from=venv /opt/venv /opt/venv" in runtime
    assert "--require-hashes" in text


def test_dockerfile_guard_flags_tooling_in_runtime_stage():
    guard = _load_guard()
    bad = "FROM python:3.12 AS a\nRUN x\nFROM a AS b\nRUN y\nFROM a AS runtime\nRUN apt-get install -y curl gnupg\nRUN pip install x\n"
    problems = guard.api_dockerfile_problems(bad)
    assert any("curl" in p for p in problems) and any("pip install" in p for p in problems)
    assert guard.api_dockerfile_problems("FROM python:3.12\n")  # single stage is rejected


def test_pin_images_finds_every_image_and_skips_stage_aliases(tmp_path):
    pin = _load_script("pin_images")
    (tmp_path / "apps/x").mkdir(parents=True)
    (tmp_path / "apps/x/Dockerfile").write_text("FROM python:3.12-slim AS base\nFROM base AS build\nFROM scratch\nFROM nginx:1.27-alpine\n")
    (tmp_path / "docker-compose.yml").write_text("services:\n  a:\n    image: redis:7-alpine\n  b:\n    image: ${X:-y}\n    build: .\n")
    names = sorted(r.ref for r in pin.find_refs(tmp_path))
    assert names == ["nginx:1.27-alpine", "python:3.12-slim", "redis:7-alpine"]


def test_pin_images_rewrite_is_idempotent_and_refresh_moves_pins(tmp_path):
    pin = _load_script("pin_images")
    old, new = "sha256:" + "a" * 64, "sha256:" + "b" * 64
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(f"services:\n  a:\n    image: redis:7-alpine\n  b:\n    image: caddy:2-alpine@{old}  # keep\n")
    digests = {"redis:7-alpine": "sha256:" + "c" * 64, "caddy:2-alpine": new}
    refs = pin.find_refs(tmp_path)
    assert pin.rewrite(tmp_path, refs, digests, refresh=False) == 1  # only the unpinned one
    text = compose.read_text()
    assert "redis:7-alpine@sha256:" + "c" * 64 in text and f"caddy:2-alpine@{old}  # keep" in text
    assert pin.rewrite(tmp_path, pin.find_refs(tmp_path), digests, refresh=False) == 0  # idempotent
    assert pin.rewrite(tmp_path, pin.find_refs(tmp_path), digests, refresh=True) == 1  # refresh moves caddy
    assert f"caddy:2-alpine@{new}  # keep" in compose.read_text()


def test_image_pins_are_all_or_nothing():
    pins = _load_guard().image_pin_problems()
    assert pins == [], pins


def test_every_compose_service_is_memory_capped_within_budget():
    import yaml

    guard = _load_guard()
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert guard.memory_problems(compose) == []
    total = sum(guard._mib(s["mem_limit"]) for s in compose["services"].values())
    assert total == guard.MEMORY_BUDGET_MIB == 3584
    assert "3584 MiB" in (ROOT / "docs/RUNBOOK.md").read_text()


def test_memory_guard_flags_uncapped_service_overbudget_and_unbounded_redis():
    guard = _load_guard()
    compose = {
        "services": {
            "redis": {"mem_limit": "256m", "command": "redis-server --appendonly yes"},
            "bot": {"image": "x"},
            "big": {"mem_limit": "4g"},
        }
    }
    problems = " | ".join(guard.memory_problems(compose))
    assert "'bot' has no mem_limit" in problems
    assert "exceeds the" in problems
    assert "redis needs --maxmemory" in problems and "noeviction" in problems


def test_redis_maxmemory_is_below_its_container_cap():
    import yaml

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["redis"]
    assert "--maxmemory 160mb" in compose["command"] and compose["mem_limit"] == "256m"


def test_deploy_script_limits_parallel_image_builds():
    assert "COMPOSE_PARALLEL_LIMIT" in (ROOT / "scripts/deploy.sh").read_text()
