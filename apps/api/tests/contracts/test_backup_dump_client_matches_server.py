"""r15 restore-drill finding: the api image carries pg clients 16 and 17; a dump made by 17 cannot be restored into the PostgreSQL 16 server."""

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "backup_secure.sh"


def test_backup_dumps_with_the_client_matching_the_server_major():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "show server_version_num" in text
    assert "/usr/lib/postgresql/${server_num:0:2}/bin/pg_dump" in text
    assert '"$PG_DUMP" --format=custom --no-owner' in text
