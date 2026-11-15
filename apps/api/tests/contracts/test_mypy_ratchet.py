"""r13: the mypy error ratchet may only shrink (docs/DECISIONS.md r13b, audit section 8.5)."""
import tomllib
from pathlib import Path

MAX_RATCHET = 9  # lower this number whenever a module is cleaned and removed from the override list


def test_mypy_ratchet_only_shrinks():
    cfg = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8"))
    mypy = cfg["tool"]["mypy"]
    ratchet = [m for o in mypy["overrides"] if o.get("ignore_errors") for m in o["module"]]
    assert len(ratchet) <= MAX_RATCHET, "do not add modules to the mypy ratchet; fix the typing instead"
    for pkg in ("orders", "identity", "reseller"):
        assert f"melorin/modules/{pkg}" in mypy["files"]
