"""Guard: the test-suite speed-up for scrypt (tests/conftest.py) must never leak into the production default."""

import ast
from pathlib import Path

SECURITY = Path(__file__).resolve().parents[1] / "melorin" / "core" / "security.py"


def _const(expr: ast.expr) -> int:
    """Evaluate a constant integer expression such as ``2**14`` without executing arbitrary code."""
    if isinstance(expr, ast.Constant):
        return expr.value
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Pow):
        return _const(expr.left) ** _const(expr.right)
    raise AssertionError(f"unsupported expression: {ast.dump(expr)}")


def test_production_source_keeps_the_hardened_scrypt_cost():
    tree = ast.parse(SECURITY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_SCRYPT" for t in node.targets):
            kwargs = {k.arg: _const(k.value) for k in node.value.keywords}
            assert kwargs["n"] >= 2**14 and kwargs["r"] >= 8 and kwargs["dklen"] >= 32
            return
    raise AssertionError("_SCRYPT definition not found in melorin/core/security.py")


async def test_hash_roundtrip_still_works_with_the_cheap_test_factor():
    from melorin.core.security import hash_password, verify_password

    stored = await hash_password("correct-horse-battery-staple")
    assert await verify_password("correct-horse-battery-staple", stored)
    assert not await verify_password("wrong", stored)
