"""Frozen initial Melorin schema.

The source fingerprint prevents model changes from silently changing 0001.
Future schema changes must be explicit Alembic revisions.
"""
import hashlib
from pathlib import Path

from alembic import op
from sqlalchemy.schema import CreateIndex, CreateTable

from melorin.core.db import Base
from melorin import models  # noqa: F401, register every model before baseline DDL

# BASELINE_SCHEMA_CONTRACT: frozen and regression-tested.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None
MODEL_SOURCE_FINGERPRINT = "a679a521f9931de7f44afad5082ddaa068f004ed8ff7e2937295ce18995ec6cc"


def _model_source_fingerprint() -> str:
    root = Path(__file__).resolve().parents[2] / "melorin"
    files = [root / "core" / "db.py", *sorted(root.glob("modules/*/models.py"))]
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def upgrade() -> None:
    if _model_source_fingerprint() != MODEL_SOURCE_FINGERPRINT:
        raise RuntimeError(
            "0001_initial is frozen; model sources changed. Add an explicit Alembic revision "
            "or intentionally regenerate the baseline fingerprint."
        )
    for table in Base.metadata.sorted_tables:
        op.execute(CreateTable(table))
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            op.execute(CreateIndex(index))


def downgrade() -> None:
    # Deliberately non-destructive. The original bootstrap migration used
    # A destructive downgrade could destroy an entire database, so it is blocked.
    raise RuntimeError("0001_initial downgrade is intentionally blocked; restore a backup or use an explicit rollback migration")
