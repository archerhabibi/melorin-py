"""I35 test matrix runner.

Runs fast tests by default and makes integration/E2E/security/concurrency
groups explicit, so missing runtime evidence cannot hide behind unit tests.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


GROUPS = {
    "unit": ["-m", "not integration"],
    "integration": ["-m", "integration"],
    "concurrency": ["-m", "concurrency"],
    "all": [],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("group", choices=GROUPS, default="unit", nargs="?")
    args = parser.parse_args()
    cmd = [sys.executable, "-m", "pytest", "-q", *GROUPS[args.group]]
    if os.getenv("MELORIN_COVERAGE", "1") == "1" and args.group in {"unit", "all"}:
        cmd[3:3] = ["--cov=melorin", "--cov-report=term-missing", "--cov-report=xml"]
    api = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps", "api")
    return subprocess.call(cmd, cwd=api)


if __name__ == "__main__":
    raise SystemExit(main())
