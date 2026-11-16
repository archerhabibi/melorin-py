from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[2]


def test_admin_requires_2fa_and_totp_replay_state_is_persisted():
    deps = read_source(ROOT / "melorin/core/deps.py")
    model = read_source(ROOT / "melorin/kernel/models/identity.py")
    security = read_source(ROOT / "melorin/core/security.py")
    router = read_source(ROOT / "melorin/modules/identity/router.py")
    assert "ADMIN_2FA_REQUIRED" in deps
    assert "totp_last_counter" in model
    assert "def totp_counter" in security
    assert "counter <= user.totp_last_counter" in router
    assert "with_for_update()" in router


