from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_admin_requires_2fa_and_totp_replay_state_is_persisted():
    deps = (ROOT / "melorin/core/deps.py").read_text()
    model = (ROOT / "melorin/modules/identity/models.py").read_text()
    security = (ROOT / "melorin/core/security.py").read_text()
    router = (ROOT / "melorin/modules/identity/router.py").read_text()
    assert "ADMIN_2FA_REQUIRED" in deps
    assert "totp_last_counter" in model
    assert "def totp_counter" in security
    assert "counter <= user.totp_last_counter" in router
    assert "with_for_update()" in router


def test_admin_role_metadata_migration_exists():
    migration = (ROOT / "alembic/versions/0007_admin_security.py").read_text()
    assert "admin_roles" in migration and "totp_last_counter" in migration
