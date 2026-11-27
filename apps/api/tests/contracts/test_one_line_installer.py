"""Contracts for the one-line installer (get.sh -> melorin.sh -> scripts/install_server.sh, scripts/lib/common.sh).

These tests RUN the shell code (no Docker, no root, no network needed): a bootstrap that only looks right when read has failed
people before - it died with exit code 0 and nothing installed when there was no terminal, and a half-downloaded get.sh
executed half of itself.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
GET = ROOT / "get.sh"
MELORIN = ROOT / "melorin.sh"
INSTALL = ROOT / "scripts" / "install_server.sh"
POST = ROOT / "scripts" / "post_install.sh"
LIB = ROOT / "scripts" / "lib" / "common.sh"
ALL_SCRIPTS = [GET, MELORIN, INSTALL, POST, LIB]

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required")


def sh(code: str, *, cwd: Path | None = None, env: dict | None = None, timeout: int = 60):
    """Run `code` in a fresh bash. start_new_session drops the controlling terminal: a developer running pytest in a real
    terminal must not make has_tty() true and hang a prompt."""
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", "-c", code], cwd=cwd, env=full_env, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, start_new_session=True, timeout=timeout, check=False,
    )


def lib(code: str, **kw):
    return sh(f". {LIB}\n{code}", **kw)


# ---------------------------------------------------------------- static
@pytest.mark.parametrize("script", ALL_SCRIPTS, ids=lambda p: p.name)
def test_every_installer_script_parses(script):
    assert subprocess.run(["bash", "-n", str(script)], capture_output=True, check=False).returncode == 0


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
@pytest.mark.parametrize("script", ALL_SCRIPTS, ids=lambda p: p.name)
def test_installer_scripts_are_shellcheck_clean(script):
    # warning level: the pre-existing style notes in older scripts are not this contract's business
    out = subprocess.run(["shellcheck", "-S", "warning", str(script)], capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stdout


def test_a_truncated_get_sh_does_nothing():
    """The network can cut the download at any line. Every prefix that ends at a function boundary is valid bash: it must define
    functions and run nothing (a top-to-bottom script would have executed half of itself)."""
    lines = GET.read_text().splitlines()
    assert lines[-1] == 'if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then main "$@"; fi'
    cuts = [i for i, ln in enumerate(lines) if ln == "}"]
    assert len(cuts) > 10
    for i in cuts[:: max(1, len(cuts) // 12)]:
        out = sh("\n".join(lines[: i + 1]))
        assert (out.returncode, out.stdout, out.stderr) == (0, "", ""), f"prefix ending at line {i + 1} executed something"


def test_sourcing_get_sh_loads_functions_and_runs_nothing():
    out = sh(f". {GET}; type -t main; type -t latest_release_tag; echo done")
    assert out.returncode == 0
    assert out.stdout.split() == ["function", "function", "done"], out.stdout + out.stderr


def test_the_menu_never_redirects_from_dev_tty_on_file_existence_alone():
    """`[ -r /dev/tty ]` is true even without a terminal (the node always exists); the redirect then killed the script."""
    text = MELORIN.read_text()
    assert "[ -r /dev/tty ]" not in text
    assert "has_tty" in text
    assert "has_tty() { ( : </dev/tty ) 2>/dev/null; }" in LIB.read_text()


# ---------------------------------------------------------------- get.sh behaviour
def test_get_sh_help_needs_no_root_no_network_and_exits_zero():
    out = sh(f"bash {GET} --help")
    assert out.returncode == 0
    assert "install --domain" in out.stdout and "--commit SHA" in out.stdout


@pytest.mark.parametrize(
    "args, needle",
    [
        ("--bogus", "Unknown option"),
        ("--ref ../etc", "Invalid ref"),
        ("--commit abc123", "full 40-character"),  # an abbreviated SHA is not a pin
        ("--dir /", "Refusing"),
        ("--dir relative/path", "absolute path"),
    ],
)
def test_get_sh_rejects_bad_input_before_touching_anything(args, needle):
    out = sh(f"bash {GET} {args}")
    assert out.returncode != 0
    assert needle in out.stderr, out.stderr


def _git(repo: Path, *args: str):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "-C", str(repo), *args],
        check=True, capture_output=True,
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_sudo_that_needs_a_password_without_a_terminal_fails_with_a_clear_message():
    """Non-root + sudo asking for a password + no terminal (cloud-init, ssh without -t): sudo's own 'a terminal is required'
    is cryptic, so get.sh checks `sudo -n` / /dev/tty first and says what to do."""
    text = GET.read_text()
    assert "sudo -n true" in text and "no terminal to ask it on" in text


def test_doctor_is_not_described_as_installing_nothing():
    """doctor changes no Melorin state, but get.sh does fetch the project and git/curl/openssl first: the help must not lie."""
    assert "installs nothing" not in GET.read_text()


def test_latest_release_tag_is_strict_semver_and_version_sorted(tmp_path):
    """v1.10.0 beats v1.9.0 (version sort), and a release candidate is neither the newest nor a release."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "x")
    for tag in ("v1.9.0", "v1.10.0", "v2.0.0-rc1", "v1.10.0-beta", "vNext", "nightly"):
        _git(tmp_path, "tag", tag)
    out = sh(f'. {GET}; latest_release_tag "{tmp_path}"')
    assert out.stdout.strip() == "v1.10.0", out.stderr
    empty = tmp_path / "empty"
    empty.mkdir()
    _git(empty, "init", "-q")
    assert sh(f'. {GET}; latest_release_tag "{empty}"').stdout.strip() == ""


# ---------------------------------------------------------------- melorin.sh behaviour (needs root: the script refuses otherwise)
needs_root = pytest.mark.skipif(os.geteuid() != 0, reason="melorin.sh requires root")


@needs_root
def test_menu_without_a_terminal_explains_and_exits_2_not_0():
    out = sh(f"bash {MELORIN}")
    assert out.returncode == 2, (out.returncode, out.stdout, out.stderr)
    assert "needs a terminal" in out.stderr and "melorin install" in out.stderr


@needs_root
def test_unattended_install_validates_everything_before_starting():
    out = sh(
        f"bash {MELORIN} install --domain 'not a domain' --admin-domain a.example.com --email me@x.test --admin-tg @name --yes",
        env={"MELORIN_FORCE": "1"},
    )
    assert out.returncode == 2
    for needle in ("--domain:", "--email:", "--admin-tg"):
        assert needle in out.stderr, out.stderr
    assert "Usage: melorin install" in out.stderr


@needs_root
def test_bot_token_is_refused_on_the_command_line():
    out = sh(f"bash {MELORIN} install --bot-token 123456789:AAexample --yes", env={"MELORIN_FORCE": "1"})
    assert out.returncode == 2 and "MAIN_BOT_TOKEN" in out.stderr


@needs_root
def test_melorin_sh_refuses_to_run_as_a_copy(tmp_path):
    """A COPY resolves APP_DIR to its own folder; uninstall would then delete that folder."""
    copy = tmp_path / "melorin"
    shutil.copy(MELORIN, copy)
    out = sh(f"bash {copy} uninstall")
    assert out.returncode == 1 and "inside a Melorin checkout" in out.stderr
    assert copy.exists()


# ---------------------------------------------------------------- library behaviour
@pytest.mark.parametrize(
    "domain, ok",
    [
        ("shop.example.com", True), ("a.b.c.example.org", True), ("shop.example.xn--p1ai", True),
        ("localhost", False), ("a b.com", False), ("-a.example.com", False), ("a_b.example.com", False),
        ("a" * 64 + ".com", False), ("example", False), ("", False),
    ],
)
def test_valid_domain(domain, ok):
    assert lib(f'valid_domain "{domain}"').returncode == (0 if ok else 1)


@pytest.mark.parametrize(
    "email, ok",
    [("me@example.com", True), ("a.b+c@mail.example.org", True), ("me@x.test", False), ("me@host.local", False),
     ("me@a.onion", False), ("me@localhost", False), ("no-at-sign", False)],
)
def test_valid_email_refuses_special_use_domains(email, ok):
    """V-004: the app's login validator rejects them, so the admin account would be created and never able to sign in."""
    assert lib(f'valid_email "{email}"').returncode == (0 if ok else 1)


def test_norm_domain_strips_scheme_path_space_and_case():
    assert lib('norm_domain " HTTPS://Shop.Example.com/x/ "').stdout == "shop.example.com"


@pytest.mark.parametrize("a, b, ok", [("2.29.1", "2.20.0", True), ("2.20.0", "2.20.0", True), ("2.9.0", "2.20.0", False), ("5.8.0", "2.20.0", True)])
def test_ver_ge_compares_versions_not_strings(a, b, ok):
    assert lib(f"ver_ge {a} {b}").returncode == (0 if ok else 1)


def test_retry_retries_then_gives_up():
    ok = lib('n=0; f() { n=$((n+1)); [ $n -ge 3 ]; }; retry 4 0 f 2>/dev/null; echo "rc=$? n=$n"')
    assert ok.stdout.strip() == "rc=0 n=3"
    bad = lib('n=0; f() { n=$((n+1)); false; }; retry 3 0 f 2>/dev/null; echo "rc=$? n=$n"')
    assert bad.stdout.strip() == "rc=1 n=3"


def test_has_tty_is_false_without_a_controlling_terminal():
    assert lib("has_tty").returncode == 1


@pytest.mark.skipif(shutil.which("ss") is None, reason="ss (iproute2) is required")
def test_port_owner_names_the_listener_and_reports_free_ports():
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        out = lib(f"port_owner {port}")
        assert out.returncode == 0 and out.stdout  # a name (or "another process" when the kernel hides it)
        assert lib(f"port_busy {port}").returncode == 0
    finally:
        sock.close()
    assert lib(f"port_busy {port}").returncode == 1


@pytest.mark.parametrize(
    "log, hint",
    [
        ("toomanyrequests: You have reached your pull rate limit", "docker login"),
        ("denied: requested access to the resource is denied", "mirror"),
        ("dial tcp 1.2.3.4:443: i/o timeout", "DNS"),
        ("write /x: no space left on device", "disk is full"),
        ("process exited with signal: killed", "out of memory"),
    ],
)
def test_docker_failure_hint_names_the_likely_cause(tmp_path, log, hint):
    f = tmp_path / "build.log"
    f.write_text(log + "\n")
    out = lib(f'docker_failure_hint "{f}"')
    assert out.returncode == 0 and hint.lower() in out.stderr.lower(), out.stderr


def test_unknown_build_failure_has_no_invented_hint(tmp_path):
    f = tmp_path / "build.log"
    f.write_text("SyntaxError: invalid syntax\n")
    assert lib(f'docker_failure_hint "{f}"').returncode == 1


def test_only_network_failures_are_retried(tmp_path):
    flaky, real = tmp_path / "a.log", tmp_path / "b.log"
    flaky.write_text("failed to do request: Get https://registry: net/http: TLS handshake timeout\n")
    real.write_text("ERROR: failed to solve: process \"/bin/sh -c pip install\" did not complete successfully: exit code: 1\n")
    assert lib(f'transient_failure "{flaky}"').returncode == 0
    assert lib(f'transient_failure "{real}"').returncode == 1


# ---------------------------------------------------------------- install_server.sh / post_install.sh contracts
def test_credentials_are_saved_before_the_password_can_be_lost():
    """The bootstrap password is deleted from .env once the admin exists; an SSH drop before the final summary used to lose it."""
    text = INSTALL.read_text()
    saved = text.index('save_credentials "$BOOTSTRAP_PASSWORD" "$BOOTSTRAP_TOTP"')
    assert saved < text.index("build_images || exit 1") < text.index("sed -i '/^MELORIN_BOOTSTRAP_ADMIN_PASSWORD=/d' .env")


def test_installer_survives_a_dropped_connection_and_runs_one_at_a_time():
    text = INSTALL.read_text()
    assert "trap '' HUP" in text and "flock -n 9" in text
    assert "setsid -f" in MELORIN.read_text()


def test_a_repair_rerun_does_not_bootstrap_again():
    """The password is gone from .env after the first success: bootstrap must be conditional or the repair path always died."""
    text = INSTALL.read_text()
    guard = text.index("if grep -q '^MELORIN_BOOTSTRAP_ADMIN_PASSWORD=' .env; then\n  compose run -T --rm api python -m melorin.cli bootstrap")
    assert guard > text.index("alembic upgrade head")


def test_installer_has_no_pipe_to_shell_and_no_token_on_a_command_line():
    import re

    for script in (INSTALL, LIB):  # (get.sh documents the `curl | sudo bash` USAGE in its header; it never does it itself)
        code = [ln for ln in script.read_text().splitlines() if not ln.lstrip().startswith("#")]
        assert not [ln for ln in code if re.search(r"curl[^|]*\|\s*(sudo\s+)?(ba)?sh\b", ln)], script.name
        assert not [ln for ln in code if "get.docker.com" in ln], script.name
    assert "curl -fsS -m 10 -K -" in INSTALL.read_text()  # the Telegram URL (with the token) goes through stdin
    assert 'bot${BOT}/getMe" >' not in INSTALL.read_text()


def test_docker_is_checked_for_compose_daemon_and_version_not_just_the_binary():
    text = LIB.read_text()
    for needle in ("docker compose version", "docker info", "MIN_COMPOSE_VERSION", "docker-compose-plugin", "download.docker.com"):
        assert needle in text, needle
    assert "ensure_docker || exit 1" in INSTALL.read_text()


def test_apt_never_blocks_on_the_dpkg_lock_or_a_dialog():
    text = LIB.read_text()
    assert "DPkg::Lock::Timeout=300" in text and "NEEDRESTART_MODE=l" in text and "DEBIAN_FRONTEND=noninteractive" in text
    assert "DPkg::Lock::Timeout=300" in GET.read_text()


def test_firewall_is_never_enabled_without_a_confirmed_ssh_port():
    text = POST.read_text()
    assert "no SSH listener detected" in text
    assert "SSH_CONNECTION" in text and "sshd -T" in text


def test_checkout_mode_bits_do_not_dirty_the_tree():
    """get.sh chmods scripts; without core.fileMode=false git shows the scripts that are not +x in git as modified."""
    for script in (GET, INSTALL):
        assert "core.fileMode false" in script.read_text(), script.name
    assert "core.fileMode false" in MELORIN.read_text()  # heals installs made before the fix
