from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cors_is_explicit_not_wildcarded():
    app = (ROOT / "melorin/app.py").read_text()
    config = (ROOT / "melorin/core/config.py").read_text()
    assert "allow_methods=s.cors_allow_methods" in app
    assert "allow_headers=s.cors_allow_headers" in app
    assert "cors_allow_methods" in config and "cors_allow_headers" in config
    assert "CORS wildcard origins, methods, and headers are not allowed" in config
