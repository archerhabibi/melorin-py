"""Browser-security contracts for direct Nginx and the bundled Caddy proxy."""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import pytest

PROJECT = Path(__file__).resolve().parents[4]
WEB_APPS = ("store-web", "admin-web")
CADDY = (PROJECT / "infra/Caddyfile").read_text(encoding="utf-8")


def _caddy_headers(name: str) -> list[str]:
    pattern = rf'^\s*{name}\s+"?([^"\n]+?)"?\s*$'
    return [match.group(1) for match in re.finditer(pattern, CADDY, re.M)]


def _nginx_header(conf: str, name: str) -> str:
    match = re.search(rf'add_header\s+{name}\s+"([^\"]*)"\s+always;', conf)
    assert match, f"{name} is missing from Nginx"
    return match.group(1)


@pytest.mark.parametrize("name", ["Content-Security-Policy", "Cross-Origin-Opener-Policy"])
def test_web_security_headers_match_the_proxy(name: str):
    proxy_headers = _caddy_headers(name)
    assert len(proxy_headers) == 3 and len(set(proxy_headers)) == 1
    for app in WEB_APPS:
        conf = (PROJECT / "apps" / app / "nginx.conf").read_text(encoding="utf-8")
        assert _nginx_header(conf, name) == proxy_headers[0], app


def test_csp_does_not_allow_unsafe_inline_scripts():
    policy = _caddy_headers("Content-Security-Policy")[0]
    scripts = next(part for part in policy.split(";") if part.strip().startswith("script-src"))
    assert "'unsafe-inline'" not in scripts
    assert "'unsafe-eval'" not in scripts
    assert "default-src 'self'" in policy


@pytest.mark.integration
@pytest.mark.parametrize("app", WEB_APPS)
def test_nginx_responses_keep_security_headers_on_assets_and_errors(app: str, tmp_path: Path):
    """Set MELORIN_TEST_NGINX_IMAGE to an installed image to exercise a real server."""
    image = os.environ.get("MELORIN_TEST_NGINX_IMAGE")
    docker = shutil.which("docker")
    if not image or not docker:
        pytest.skip("set MELORIN_TEST_NGINX_IMAGE and provide Docker for the Nginx runtime test")

    site = tmp_path / "site"
    (site / "assets").mkdir(parents=True)
    (site / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (site / "assets" / "app.js").write_text("ok", encoding="utf-8")
    conf = PROJECT / "apps" / app / "nginx.conf"
    result = subprocess.run(
        [
            docker,
            "run",
            "--rm",
            "--detach",
            "--pull=never",
            "--add-host",
            "api:127.0.0.1",
            "--publish",
            "127.0.0.1::80",
            "--volume",
            f"{conf}:/etc/nginx/conf.d/default.conf:ro",
            "--volume",
            f"{site}:/usr/share/nginx/html:ro",
            image,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    container = result.stdout.strip()
    try:
        port = (
            subprocess.run(
                [docker, "port", container, "80/tcp"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            .stdout.strip()
            .splitlines()[0]
            .rsplit(":", 1)[1]
        )
        base = f"http://127.0.0.1:{port}"
        for attempt in range(30):
            try:
                with urlopen(base + "/", timeout=1):
                    break
            except (URLError, TimeoutError):
                if attempt == 29:
                    raise
                time.sleep(0.1)

        for path, expected_status in (("/", 200), ("/assets/app.js", 200), ("/api/v1/internal/private", 404)):
            try:
                response = urlopen(base + path, timeout=5)
            except HTTPError as error:
                response = error
            with response:
                assert response.status == expected_status
                assert response.headers["Content-Security-Policy"] == _caddy_headers("Content-Security-Policy")[0]
                assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin-allow-popups"
                assert response.headers["X-Content-Type-Options"] == "nosniff"
                assert response.headers["X-Frame-Options"] == "DENY"
                assert response.headers["Strict-Transport-Security"]
                assert response.headers["Referrer-Policy"]
                assert response.headers["Permissions-Policy"]
                if path.startswith("/assets/"):
                    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"
                else:
                    assert response.headers.get("Cache-Control") is None
    finally:
        subprocess.run([docker, "rm", "--force", container], capture_output=True, check=False, timeout=15)
