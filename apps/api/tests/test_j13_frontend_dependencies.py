import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[3]


def test_frontend_runtime_and_build_dependencies_are_separated():
    for name in ("apps/store-web/package.json", "apps/admin-web/package.json"):
        package = json.loads((PROJECT / name).read_text())
        assert set(package["dependencies"]) <= {"react", "react-dom", "lucide-react"}
        assert "vite" in package["devDependencies"]
        assert "postcss" in package["devDependencies"]
        assert "tailwindcss" in package["devDependencies"]


def test_ci_audits_both_frontends():
    ci = (PROJECT / ".github/workflows/ci.yml").read_text()
    assert ci.count("npm audit --audit-level=high") == 2
