import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_password_kdf_is_async_and_offloaded():
    security = (ROOT / "melorin/core/security.py").read_text()
    router = (ROOT / "melorin/modules/identity/router.py").read_text()
    cli = (ROOT / "melorin/cli.py").read_text()
    assert "async def hash_password" in security
    assert "async def verify_password" in security
    assert "asyncio.to_thread" in security
    assert "await verify_password" in router
    assert "await hash_password" in router
    assert "await hash_password" in cli
    ast.parse(security)
