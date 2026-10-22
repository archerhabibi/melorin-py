from pathlib import Path

from _source import read_source

ROOT = Path(__file__).resolve().parents[1]


def test_cors_is_explicit_not_wildcarded():
    app = read_source(ROOT / "melorin/app.py")
    config = read_source(ROOT / "melorin/core/config.py")
    assert "allow_methods=s.cors_allow_methods" in app
    assert "allow_headers=s.cors_allow_headers" in app
    assert "cors_allow_methods" in config and "cors_allow_headers" in config
    assert "CORS wildcard origins, methods, and headers are not allowed" in config
