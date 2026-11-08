"""The shipped base subscription template: renders with and without branding, escapes everything, drops unsafe links."""

from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2")

TEMPLATE = Path(__file__).resolve().parents[3] / "infra" / "sub-template" / "index.html"


def _render(**ctx) -> str:
    env = jinja2.Environment(autoescape=False)  # worst case: the panel's own environment does not escape
    env.filters["bytesformat"] = lambda n: f"{int(n or 0)} B"
    user = type("S", (), {"value": "active"})
    base = {"user": type("U", (), {"username": "u1", "status": user, "used_traffic": 10, "data_limit": 0})(), "links": ["vless://abc"]}
    return env.from_string(TEMPLATE.read_text(encoding="utf-8")).render(**{**base, **ctx})


def test_renders_without_branding():
    html = _render()
    assert "اشتراک شما" in html and "vless://abc" in html and "<img" not in html and "پشتیبانی" not in html


@pytest.mark.parametrize("where", ["admin", "top"])
def test_reads_branding_from_either_context_name(where):
    cv = {"melorin_brand_name": "فروشگاه من", "melorin_support_url": "https://t.me/shop", "melorin_logo_url": "https://cdn.example/l.png"}
    ctx = {"admin": type("A", (), {"custom_variables": cv})()} if where == "admin" else {"custom_variables": cv}
    html = _render(**ctx)
    assert "فروشگاه من" in html and 'href="https://t.me/shop"' in html and 'src="https://cdn.example/l.png"' in html


def test_values_are_escaped_and_unsafe_links_dropped():
    cv = {"melorin_brand_name": "<script>alert(1)</script>", "melorin_support_url": "javascript:alert(1)", "melorin_logo_url": "http://x/l.png"}
    html = _render(custom_variables=cv)
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert "javascript:" not in html and "<img" not in html


def test_no_script_and_no_external_requests():
    html = _render()
    assert "<script" not in html and "default-src 'none'" in html
