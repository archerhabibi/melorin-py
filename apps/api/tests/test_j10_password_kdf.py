import ast
from pathlib import Path

from _source import parse_source, read_source

ROOT = Path(__file__).resolve().parents[1]


def test_password_kdf_is_async_and_offloaded():
    security = read_source(ROOT / "melorin/core/security.py")
    router = read_source(ROOT / "melorin/modules/identity/router.py")
    cli = read_source(ROOT / "melorin/cli.py")
    assert "async def hash_password" in security
    assert "async def verify_password" in security
    assert "asyncio.to_thread" in security
    assert "await verify_password" in router
    assert "await hash_password" in router
    assert "await hash_password" in cli
    parse_source(ROOT / "melorin/core/security.py")
