#!/usr/bin/env python3
"""Generate the two machine-owned documents and guard documentation hygiene.

    python scripts/gen_docs.py            # (re)write docs/STATUS.md and the generated block of docs/API.md
    python scripts/gen_docs.py --check    # verify nothing is stale / mis-filed (used by CI and `make guards`)

Machine-owned content (never edit by hand):
  * docs/STATUS.md                          - migration head, API surface, tests, coverage, docs inventory
  * docs/API.md between the GENERATED markers - every route, read from the live FastAPI OpenAPI schema

`--check` fails when:
  1. the generated route block in docs/API.md differs from the code,
  2. the migration head / API operation count in docs/STATUS.md differs from the code,
  3. a status carrier (README*, CONTRIBUTING, active docs) hard-codes an Alembic head,
  4. a phase report (Melorin_*.md and similar) is filed in docs/ root instead of docs/history/,
  5. an active document points at a docs/*.md file that does not exist.

Volatile numbers (test count, coverage) are written but deliberately NOT checked, so that adding a
test never turns CI red. Coverage is read from apps/api/coverage.xml when CI produced one.
"""

from __future__ import annotations

import ast
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
DOCS = ROOT / "docs"
BEGIN = "<!-- BEGIN GENERATED ROUTES (scripts/gen_docs.py) -->"
END = "<!-- END GENERATED ROUTES -->"
METHODS = ("get", "post", "put", "patch", "delete", "head")


# --------------------------------------------------------------------------- measurements
def alembic_head() -> tuple[str, int]:
    """Return (head revision, number of migrations) by reading the version files statically."""
    revs: dict[str, tuple[str, ...]] = {}
    for path in sorted((API / "alembic" / "versions").glob("*.py")):
        tree = ast.parse(path.read_text())
        rev: str | None = None
        down: tuple[str, ...] = ()
        for node in tree.body:
            target = value = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target, value = node.target.id, node.value
            if target == "revision" and value is not None:
                rev = ast.literal_eval(value)
            elif target == "down_revision" and value is not None:
                lit = ast.literal_eval(value)
                down = () if lit is None else ((lit,) if isinstance(lit, str) else tuple(lit))
        if rev:
            revs[rev] = down
    parents = {p for downs in revs.values() for p in downs}
    heads = sorted(r for r in revs if r not in parents)
    if len(heads) != 1:
        raise SystemExit(f"expected exactly one Alembic head, found {heads}")
    return heads[0], len(revs)


def load_app():
    """Import the FastAPI app without touching a database (routing only)."""
    os.environ.setdefault("MELORIN_ENV", "development")
    os.environ.setdefault("MELORIN_ALLOW_MOCK_PROVIDERS", "true")
    os.environ.setdefault("MELORIN_DATABASE_URL", "postgresql+asyncpg://melorin:melorin@localhost:5432/melorin")
    os.environ.setdefault("MELORIN_JWT_SECRET", "docs-generation-only-secret-not-used-at-runtime")
    sys.path.insert(0, str(API))
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from melorin.app import app
        from melorin.models import Base

        return app.openapi(), len(Base.metadata.tables)


def routes(schema: dict) -> list[tuple[str, str, str, str]]:
    rows = []
    for path, item in schema["paths"].items():
        for method in METHODS:
            op = item.get(method)
            if not op:
                continue
            tags = op.get("tags") or ["untagged"]
            rows.append((tags[-1], path, method.upper(), op.get("summary") or op.get("operationId", "")))
    return sorted(rows, key=lambda r: (r[0], r[1], METHODS.index(r[2].lower())))


def test_counts() -> tuple[int, int]:
    files = sorted((API / "tests").rglob("test_*.py"))
    funcs = 0
    for f in files:
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                funcs += 1
    return len(files), funcs


def coverage() -> str:
    cov = API / "coverage.xml"
    if not cov.is_file():
        return "not measured here (CI writes `apps/api/coverage.xml`; run `pytest --cov=melorin --cov-report=xml`)"
    root = ET.parse(cov).getroot()
    line = float(root.get("line-rate", 0)) * 100
    branch = float(root.get("branch-rate", 0)) * 100
    return f"{line:.1f} % statements, {branch:.1f} % branches (from `apps/api/coverage.xml`)"


def doc_inventory() -> dict[str, int]:
    root_md = [p for p in ROOT.glob("*.md")]
    docs_root = [p for p in DOCS.glob("*.md")]
    hist = [p for p in (DOCS / "history").glob("*.md")]
    return {"root": len(root_md), "docs": len(docs_root), "history": len(hist)}


# --------------------------------------------------------------------------- rendering
def render_route_block(rows: list[tuple[str, str, str, str]]) -> str:
    out = [BEGIN, ""]
    groups: dict[str, list] = {}
    for tag, path, method, summary in rows:
        groups.setdefault(tag, []).append((method, path, summary))
    for tag in sorted(groups):
        out += [f"### `{tag}` ({len(groups[tag])})", "", "| Method | Path | Operation |", "|---|---|---|"]
        out += [f"| {m} | `{p}` | {s} |" for m, p, s in groups[tag]]
        out.append("")
    out.append(END)
    return "\n".join(out)


def render_status(head: str, n_mig: int, schema: dict, n_tables: int, rows: list) -> str:
    n_ops = len(rows)
    n_paths = len(schema["paths"])
    t_files, t_funcs = test_counts()
    inv = doc_inventory()
    return f"""# Melorin - Generated Status

> **Machine-owned file.** Regenerate with `python scripts/gen_docs.py`; CI fails (`--check`) if the
> migration head or API surface below is stale. Release approval is **not** stated here - the only
> release-status source is `docs/RELEASE-EVIDENCE-MATRIX.md`.

| Measurement | Value |
|---|---|
| Alembic head | `{head}` |
| Migrations | {n_mig} |
| ORM tables | {n_tables} |
| API operations | {n_ops} |
| API paths | {n_paths} |
| Test files / test functions (static count) | {t_files} / {t_funcs} |
| Coverage | {coverage()} |
| Documents: repo root / `docs/` / `docs/history/` | {inv["root"]} / {inv["docs"]} / {inv["history"]} |

Where things live: requirements and design `docs/01`-`docs/17`; route list `docs/API.md`;
operations `docs/RUNBOOK.md`; decisions `docs/DECISIONS.md`; change log `docs/CHANGE_LOG.md`;
historical phase reports (evidence, never current status) `docs/history/`.
"""


# --------------------------------------------------------------------------- API.md assembly
def build_api_md(block: str) -> str:
    target = DOCS / "API.md"
    if target.is_file():
        text = target.read_text()
        if BEGIN in text and END in text:
            head, rest = text.split(BEGIN, 1)
            _, tail = rest.split(END, 1)
            return head + block + tail
    raise SystemExit("docs/API.md is missing its GENERATED markers; restore the file from git")


# --------------------------------------------------------------------------- guards
ACTIVE_DOCS = lambda: [ROOT / n for n in ("README.md", "README.fa.md", "CONTRIBUTING.md")] + [  # noqa: E731
    p for p in sorted(DOCS.glob("*.md")) if p.name not in ("CHANGE_LOG.md", "STATUS.md")
]
HEAD_LITERAL = re.compile(r"(?i)\bhead\b[^.\n]{0,60}\b00\d\d(?:_[a-z0-9_]+)?\b|\b00\d\d_[a-z0-9_]+\b[^.\n]{0,30}\bhead\b")
PHASE_REPORT = re.compile(r"^(Melorin_.*|FINAL_.*REPORT.*|REVIEW_CHANGES_.*|FULL_PROJECT_AUDIT.*)\.md$")
DOC_REF = re.compile(r"`(docs/[A-Za-z0-9_./-]+\.md)`")


def check(block: str, status_expected: str) -> list[str]:
    problems: list[str] = []
    api_md = DOCS / "API.md"
    if not api_md.is_file() or build_api_md(block) != api_md.read_text():
        problems.append("docs/API.md route block is stale - run: python scripts/gen_docs.py")
    status = DOCS / "STATUS.md"
    if not status.is_file():
        problems.append("docs/STATUS.md is missing - run: python scripts/gen_docs.py")
    else:
        for key in ("Alembic head", "API operations", "API paths", "Migrations", "ORM tables"):
            exp = next(l for l in status_expected.splitlines() if l.startswith(f"| {key} |"))
            if exp not in status.read_text().splitlines():
                problems.append(f"docs/STATUS.md row '{key}' is stale - run: python scripts/gen_docs.py")
    for doc in ACTIVE_DOCS():
        text = doc.read_text()
        rel = doc.relative_to(ROOT)
        if HEAD_LITERAL.search(text):
            problems.append(f"{rel}: hard-codes an Alembic head; point to docs/STATUS.md instead")
        for ref in DOC_REF.findall(text):
            if not (ROOT / ref).is_file():
                problems.append(f"{rel}: references missing file {ref}")
    for p in DOCS.glob("*.md"):
        if PHASE_REPORT.match(p.name):
            problems.append(f"docs/{p.name}: phase reports belong in docs/history/")
    for stale in ("FULL_PROJECT_AUDIT.md", "DOCUMENTATION-STATUS.md"):
        if (ROOT / stale).exists():
            problems.append(f"{stale}: superseded by docs/STATUS.md and must not return")
    return problems


def main() -> int:
    head, n_mig = alembic_head()
    schema, n_tables = load_app()
    rows = routes(schema)
    block = render_route_block(rows)
    status = render_status(head, n_mig, schema, n_tables, rows)
    if "--check" in sys.argv:
        problems = check(block, status)
        for p in problems:
            print(f"FAIL: {p}")
        if problems:
            return 1
        print(f"docs guard passed (head {head}, {len(rows)} operations)")
        return 0
    (DOCS / "STATUS.md").write_text(status)
    (DOCS / "API.md").write_text(build_api_md(block))
    print(f"wrote docs/STATUS.md and docs/API.md (head {head}, {len(rows)} operations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
