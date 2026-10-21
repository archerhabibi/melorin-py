"""Phase 2 (code hygiene, audit S01 section 6): guards that keep the cleanup from regressing."""

import ast
from pathlib import Path

import httpx
import pytest

API = Path(__file__).resolve().parents[1]
REPO = API.parents[1]
PACKAGE = API / "melorin"


def _python_sources():
    return [p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts]


def test_openapi_operation_ids_are_unique():
    from melorin.app import app

    ids = [
        op["operationId"]
        for item in app.openapi()["paths"].values()
        for op in item.values()
        if isinstance(op, dict) and "operationId" in op
    ]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"duplicate OpenAPI operationId: {duplicates}"


def test_payment_callback_has_one_explicit_operation_per_method():
    from melorin.app import app

    callbacks = app.openapi()["paths"]["/api/v1/payments/callbacks/{provider}"]
    assert {m: callbacks[m]["operationId"] for m in ("get", "post")} == {
        "get": "payment_callback_get",
        "post": "payment_callback_post",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/health/live", "/healthz"])
async def test_health_live_answers_get_and_head(path):
    from melorin.app import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        got = await client.get(path)
        head = await client.head(path)
    assert got.status_code == 200
    assert head.status_code == 200
    assert head.content == b""


def test_head_health_routes_are_not_published_in_openapi():
    from melorin.app import app

    assert "head" not in app.openapi()["paths"]["/health/live"]


def test_empty_partner_package_is_gone():
    assert not (PACKAGE / "modules" / "partner").exists()


def test_no_broad_except_swallows_errors_silently():
    """`except Exception: pass` (or a bare except) hides failures: log, narrow or re-raise instead."""
    offenders = []
    for path in _python_sources():
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if not isinstance(node, ast.ExceptHandler):
                continue
            broad = node.type is None or (isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"})
            if broad and all(isinstance(stmt, ast.Pass) for stmt in node.body):
                offenders.append(f"{path.relative_to(API)}:{node.lineno}")
    assert not offenders, f"silent broad except: {offenders}"


def test_dockerignore_keeps_secrets_out_and_does_not_hide_copied_paths():
    text = (REPO / ".dockerignore").read_text()
    patterns = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    for required in (".git", ".env", "secrets/", "**/node_modules"):
        assert required in patterns, f".dockerignore must exclude {required}"
    excluded = [p.rstrip("/") for p in patterns if not p.startswith(("!", "**", "*"))]
    for dockerfile in (REPO / "apps").glob("*/Dockerfile"):
        for line in dockerfile.read_text().splitlines():
            parts = line.split()
            if not parts or parts[0] != "COPY" or any(p.startswith("--from") for p in parts):
                continue
            for source in (p for p in parts[1:-1] if not p.startswith("--")):
                source = source.rstrip("/").lstrip("./")
                for pattern in excluded:
                    assert not (source == pattern or source.startswith(pattern + "/")), (
                        f"{dockerfile.parent.name}: COPY {source} is hidden by .dockerignore ({pattern})"
                    )
