#!/usr/bin/env python3
"""Fail when a web app's first-load JS exceeds its budget (Phase 6.2).

Run after ``npm run build``. "First-load JS" = the entry module script referenced by dist/index.html
plus any <link rel=modulepreload> chunks; lazily imported route chunks are not counted.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# bytes (Vite reports kB = 1000 bytes). Admin target from the S01 audit: first chunk < 300 kB.
BUDGETS = {"apps/admin-web": 300_000, "apps/store-web": 270_000}


def first_load_bytes(app: Path) -> tuple[int, list[str]]:
    dist = app / "dist"
    html = (dist / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'<script[^>]+type="module"[^>]+src="([^"]+)"', html)
    refs += re.findall(r'<link[^>]+rel="modulepreload"[^>]+href="([^"]+)"', html)
    files = [dist / ref.lstrip("/") for ref in dict.fromkeys(refs)]
    missing = [str(f) for f in files if not f.exists()]
    if missing or not files:
        raise SystemExit(f"{app}: cannot resolve entry chunks ({missing or 'none found'}); run npm run build first")
    return sum(f.stat().st_size for f in files), [f.name for f in files]


def main() -> int:
    failed = False
    for rel, budget in BUDGETS.items():
        app = ROOT / rel
        if not (app / "dist").exists():
            print(f"skip {rel}: no dist/ (build first)")
            continue
        size, names = first_load_bytes(app)
        status = "ok" if size <= budget else "OVER BUDGET"
        print(f"{rel}: first-load JS {size / 1000:.1f} kB / budget {budget / 1000:.0f} kB [{status}] {names}")
        failed |= size > budget
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
