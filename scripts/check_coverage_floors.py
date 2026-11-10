"""Per-path coverage floors (audit T39).

The global ``--cov-fail-under=75`` stays as a safety net, but money-handling code is held to a higher bar so that a
well-covered UI/admin area can no longer hide an untested ledger. Reads the ``coverage.xml`` produced by
``pytest --cov-report=xml`` and fails when any listed path prefix is below its floor.

Usage: python scripts/check_coverage_floors.py [coverage.xml]   (default: apps/api/coverage.xml)
Floors are measured as line coverage over every file whose path starts with the prefix. Raise them over time; never lower
one without a note in docs/DECISIONS.md.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET  # noqa: S405 - coverage.xml is produced by our own CI step, not external input
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# prefix (relative to the ``melorin`` package) -> minimum line coverage in percent
FLOORS: dict[str, float] = {
    "domain/": 92.0,  # pure pricing / ledger / coupon / bank-sms rules
    "modules/wallet/": 88.0,
    "modules/payments/": 85.0,
    "modules/orders/": 88.0,
    "core/uow.py": 90.0,
}


def measure(xml_path: Path) -> dict[str, tuple[int, int]]:
    """``{prefix: (covered_lines, total_lines)}`` aggregated from the report."""
    root = ET.parse(xml_path).getroot()  # noqa: S314
    totals = {p: [0, 0] for p in FLOORS}
    for cls in root.iter("class"):
        filename = cls.get("filename", "").replace("\\", "/")
        rel = filename.split("melorin/", 1)[-1]
        for prefix in FLOORS:
            if rel.startswith(prefix):
                for line in cls.iter("line"):
                    totals[prefix][1] += 1
                    if int(line.get("hits", "0")) > 0:
                        totals[prefix][0] += 1
    return {p: (c, t) for p, (c, t) in totals.items()}


def main(argv: list[str]) -> int:
    xml_path = Path(argv[1]) if len(argv) > 1 else ROOT / "apps/api/coverage.xml"
    if not xml_path.exists():
        print(f"coverage report not found: {xml_path}")
        return 2
    failed = False
    for prefix, (covered, total) in measure(xml_path).items():
        if total == 0:
            print(f"FAIL  {prefix:<22} no measured lines (path renamed? update FLOORS)")
            failed = True
            continue
        pct = 100.0 * covered / total
        ok = pct >= FLOORS[prefix]
        failed |= not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {prefix:<22} {pct:5.1f}%  (floor {FLOORS[prefix]:.0f}%, {covered}/{total} lines)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
