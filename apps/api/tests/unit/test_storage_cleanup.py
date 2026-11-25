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


@pytest.mark.parametrize("error", [OSError("disk failure"), AppError("NOT_FOUND", "missing", 404)])
async def test_cleanup_logs_expected_storage_failures(tmp_path, monkeypatch, caplog, error):
    from melorin.modules.payments.router import _discard_uncommitted_receipt

    storage = LocalStorage(str(tmp_path / "files"))

    async def fail_delete(_key):
        raise error

    monkeypatch.setattr(storage, "delete", fail_delete)
    await _discard_uncommitted_receipt(storage, "unused")
    assert "Could not remove rejected receipt upload" in caplog.text


async def test_cleanup_does_not_hide_programming_errors(tmp_path, monkeypatch):
    from melorin.modules.payments.router import _discard_uncommitted_receipt

    storage = LocalStorage(str(tmp_path / "files"))

    async def fail_delete(_key):
        raise ValueError("unexpected error")

    monkeypatch.setattr(storage, "delete", fail_delete)
    with pytest.raises(ValueError, match="unexpected error"):
        await _discard_uncommitted_receipt(storage, "unused")
