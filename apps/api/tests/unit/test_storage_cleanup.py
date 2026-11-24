"""Safe removal of a failed upload."""

import pytest

from melorin.core.errors import AppError
from melorin.core.storage import LocalStorage


async def test_delete_is_idempotent_and_cannot_escape_the_storage_root(tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep")
    storage = LocalStorage(str(tmp_path / "files"))
    key = await storage.put(b"temporary", "image/png")
    await storage.delete(key)
    await storage.delete(key)
    with pytest.raises(AppError):
        await storage.delete("../outside")
    assert outside.read_bytes() == b"keep"
