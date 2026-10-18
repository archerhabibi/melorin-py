"""Formatter-stable access to source files for "contract" tests (M6.7).

Several tests assert that a snippet exists in a source file. Comparing raw text
makes them break whenever ``ruff format`` re-wraps a line or adds a trailing
comma. ``read_source`` normalises layout-only differences so such assertions
only fail when the *code* changes.

Prefer behavioural assertions (import the object and inspect it) for new tests;
use ``read_source`` only where the property truly is "this text is in that file".
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_WS = re.compile(r"\s+")
_AFTER_OPEN = re.compile(r"([(\[{])\s+")
_BEFORE_CLOSE = re.compile(r"\s+([)\]}])")
_TRAILING_COMMA = re.compile(r",\s*([)\]}])")


def normalize_source(text: str) -> str:
    """Collapse whitespace and drop layout-only punctuation (wrapping, trailing commas)."""
    text = _WS.sub(" ", text)
    text = _TRAILING_COMMA.sub(r"\1", text)
    text = _AFTER_OPEN.sub(r"\1", text)
    text = _BEFORE_CLOSE.sub(r"\1", text)
    return text.strip()


def read_source(path: str | Path) -> str:
    """Return the normalised text of a Python source file."""
    return normalize_source(Path(path).read_text(encoding="utf-8"))


def parse_source(path: str | Path) -> ast.Module:
    """Parse a Python file from its *raw* text (normalised text is not valid Python)."""
    return ast.parse(Path(path).read_text(encoding="utf-8"))
