"""Storage abstraction (Local now, S3-compatible later). Files are private; served only via authorized endpoints."""

import hashlib
import os
import uuid
from pathlib import Path
from typing import Protocol

from melorin.core.config import get_settings
from melorin.core.errors import AppError

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


class Storage(Protocol):
    async def put(self, data: bytes, content_type: str) -> str: ...
    async def get(self, key: str) -> bytes: ...


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    async def put(self, data: bytes, content_type: str) -> str:
        key = f"{uuid.uuid4().hex[:2]}/{uuid.uuid4().hex}"
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        os.chmod(p, 0o600)
        return key

    async def get(self, key: str) -> bytes:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise AppError("NOT_FOUND", "فایل یافت نشد.", 404)
        return p.read_bytes()


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = LocalStorage(get_settings().storage_dir)
    return _storage


MAGIC = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
    "application/pdf": (b"%PDF-",),
}


def validate_upload(data: bytes, content_type: str) -> str:
    if content_type not in ALLOWED_TYPES:
        raise AppError("UNSUPPORTED_FILE", "نوع فایل مجاز نیست.", 415)
    if len(data) > get_settings().max_upload_bytes:
        raise AppError("FILE_TOO_LARGE", "حجم فایل زیاد است.", 413)
    valid_magic = any(data.startswith(prefix) for prefix in MAGIC[content_type])
    if content_type == "image/webp":
        valid_magic = valid_magic and len(data) >= 12 and data[8:12] == b"WEBP"
    if not valid_magic:
        raise AppError("INVALID_FILE_SIGNATURE", "امضای فایل با نوع اعلام‌شده مطابقت ندارد.", 415)
    return hashlib.sha256(data).hexdigest()
