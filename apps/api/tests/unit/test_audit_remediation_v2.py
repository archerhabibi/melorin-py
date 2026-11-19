from melorin.core import codes


def test_python_version_guard_present():
    import pathlib

    src = pathlib.Path(codes.__file__).parents[1].joinpath("__init__.py").read_text()
    assert "version_info < (3, 12)" in src


async def test_next_code_works_on_sqlite(tmp_path):
    from melorin.core import db

    db.configure(f"sqlite+aiosqlite:///{tmp_path}/codes.db")
    async with db.session_factory()() as session:
        await _two_codes(session)


async def _two_codes(session):
    code = await codes.next_code(session, "order_number_seq")
    assert len(code) == codes.CODE_LEN and set(code) <= set(codes.ALPHABET)
    other = await codes.next_code(session, "order_number_seq")
    assert code[:4] != other[:4]  # the local counter advances the ordering prefix


def test_repo_files_guard_secrets_and_body_size():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[4]
    assert "secrets/*" in (root / ".gitignore").read_text()
    for app in ("store-web", "admin-web"):
        conf = (root / "apps" / app / "nginx.conf").read_text()
        assert "client_max_body_size 6m" in conf and "location /assets/" in conf
    assert "9d8d4e0" not in (root / "scripts" / "install_server.sh").read_text()
    compose = (root / "docker-compose.yml").read_text()
    assert "secrets_init:" in compose and "--web.enable-lifecycle" not in compose
    assert "MelorinApiDown" in (root / "infra" / "alerts.yml").read_text()
