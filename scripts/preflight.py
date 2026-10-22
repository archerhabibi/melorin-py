"""Fail-fast toolchain preflight for local and CI verification."""
from __future__ import annotations
import argparse, shutil, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", action="store_true")
    args = parser.parse_args()
    tools = ["python3"] + (["npm", "docker"] if args.runtime else [])
    missing = [tool for tool in tools if shutil.which(tool) is None]
    files = [
        ROOT/"apps/api/requirements.txt",
        ROOT/"apps/api/requirements-dev.txt",
        ROOT/"apps/store-web/package.json",
        ROOT/"apps/admin-web/package.json",
        ROOT/"docker-compose.yml",
    ]
    missing_files = [str(p.relative_to(ROOT)) for p in files if not p.is_file()]
    if missing or missing_files:
        if missing: print("Missing tools: " + ", ".join(missing), file=sys.stderr)
        if missing_files: print("Missing files: " + ", ".join(missing_files), file=sys.stderr)
        print("Run in a complete CI/staging toolchain; no result is fabricated.", file=sys.stderr)
        return 2
    print("Preflight passed: " + ", ".join(tools)); return 0
if __name__ == "__main__": raise SystemExit(main())

healthcheck = ROOT / "scripts/telegram_healthcheck.py"
assert healthcheck.is_file(), "Telegram healthcheck script is missing"
for dockerfile in (ROOT / "apps/telegram-main/Dockerfile", ROOT / "apps/telegram-reseller/Dockerfile"):
    assert "telegram_healthcheck.py" in dockerfile.read_text(), f"{dockerfile}: healthcheck not copied into image"
