"""Fail CI when Web manifests drift or direct dependencies miss the lock graph."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

for directory in (ROOT / "apps/store-web", ROOT / "apps/admin-web"):
    package = json.loads((directory / "package.json").read_text())
    lock_path = directory / "package-lock.json"
    assert lock_path.exists(), f"{directory}: package-lock.json is missing; run npm install and commit the generated lockfile"
    lock = json.loads(lock_path.read_text())
    root = lock["packages"][""]
    assert lock["lockfileVersion"] == 3
    assert root["name"] == package["name"]
    for section in ("dependencies", "devDependencies"):
        for name, version in package.get(section, {}).items():
            assert version and version[0].isdigit(), f"{directory}: unpinned {name}={version}"
            assert root.get("dependencies", {}).get(name) == version or root.get("devDependencies", {}).get(name) == version
            assert f"node_modules/{name}" in lock["packages"], f"{directory}: {name} missing from lock graph"
            node = lock["packages"][f"node_modules/{name}"]
            assert node.get("resolved") and node.get("integrity"), f"{directory}: hollow lock entry for {name}"
print("Web lockfiles are committed, pinned, and graph-complete for direct dependencies")
