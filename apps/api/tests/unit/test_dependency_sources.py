"""pyproject.toml and requirements.in must declare the same runtime pins: ``pip install .`` and the Docker image must build the
same environment (audit V-01)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

API = Path(__file__).resolve().parents[2]


def _norm(spec: str) -> str:
    name, _, ver = spec.partition("==")
    return f"{re.sub(r'[-_.]+', '-', name.split('[')[0]).lower()}=={ver.strip()}"


def test_pyproject_dependencies_equal_requirements_in():
    declared = tomllib.loads((API / "pyproject.toml").read_text())["project"]["dependencies"]
    pins = set()
    for line in (API / "requirements.in").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            pins.add(_norm(line))
    assert {_norm(d) for d in declared} == pins
