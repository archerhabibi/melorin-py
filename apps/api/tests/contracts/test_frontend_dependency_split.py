import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]


def test_frontend_runtime_and_build_dependencies_are_separated():
    for name in ("apps/store-web/package.json", "apps/admin-web/package.json"):
        package = json.loads((PROJECT / name).read_text())
        assert set(package["dependencies"]) <= {"react", "react-dom", "lucide-react", "@fontsource-variable/vazirmatn"}
        assert "vite" in package["devDependencies"]
        assert "@tailwindcss/vite" in package["devDependencies"]
        assert "tailwindcss" in package["devDependencies"]


def test_ci_audits_both_frontends():
    ci = (PROJECT / ".github/workflows/ci.yml").read_text()
    # ADR-R2: runtime deps block at high, dev tooling at critical (picomatch has no patched release yet).
    assert ci.count("npm audit --omit=dev --audit-level=high") >= 2
    assert ci.count("npm audit --include=dev --audit-level=critical") == 2
