from pathlib import Path

from _source import read_source


def test_initial_migration_does_not_use_create_all_or_drop_all():
    source = read_source(Path(__file__).parents[1].joinpath("alembic", "versions", "0001_initial.py"))
    assert "Base.metadata.create_all" not in source
    assert "Base.metadata.drop_all" not in source
    # 0001 is a frozen static DDL snapshot: it must not compile DDL from live models.
    assert "BASELINE_DDL" in source
    assert "CREATE TABLE" in source
    assert "CREATE INDEX" in source or "CREATE UNIQUE INDEX" in source
    assert "CreateTable" not in source
    assert "CreateIndex" not in source
    assert ".compile(" not in source
    assert "conn.exec_driver_sql(statement)" in source
