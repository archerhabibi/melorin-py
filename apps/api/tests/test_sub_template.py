"""The shipped base subscription template: renders with and without branding, escapes everything, drops unsafe links.

The page context is the one PasarGuard 5.6.0 builds (read from the panel's source): ``user``, ``links``, ``announce``, ``announce_url``,
``apps``. The owner's ``custom_variables`` are reachable only as ``user.admin.custom_variables``, a LIST of ``{key, value}`` objects with
UPPER-CASE keys (``AdminContactInfo`` / ``CustomVariable``). A top-level ``custom_variables`` or ``admin`` does not exist there."""

from pathlib import Path
from types import SimpleNamespace as NS

import pytest

jinja2 = pytest.importorskip("jinja2")

TEMPLATE = Path(__file__).resolve().parents[3] / "infra" / "sub-template" / "index.html"


def cv(**pairs):
    return [NS(key=k.upper(), value=v) for k, v in pairs.items()]


def _render(variables=None, *, with_admin=True, as_dicts=False, **ctx) -> str:
    env = jinja2.Environment(autoescape=False)  # worst case: the panel's own environment does not escape
    env.filters["bytesformat"] = lambda n: f"{int(n or 0)} B"
    items = [{"key": v.key, "value": v.value} for v in (variables or [])] if as_dicts else (variables or [])
    owner = NS(username="ml_main", custom_variables=items) if with_admin else None
    user = NS(username="u1", status=NS(value="active"), used_traffic=10, data_limit=0, admin=owner)
    base = {"user": user, "links": ["vless://abc"], "announce": "", "announce_url": "", "apps": []}
    return env.from_string(TEMPLATE.read_text(encoding="utf-8")).render(**{**base, **ctx})


def test_renders_without_branding():
    html = _render()
    assert "اشتراک شما" in html and "vless://abc" in html and "<img" not in html and "پشتیبانی" not in html


def test_renders_when_the_user_has_no_owner_admin():
    html = _render(with_admin=False)
    assert "اشتراک شما" in html and "vless://abc" in html and "<img" not in html


@pytest.mark.parametrize("as_dicts", [False, True])
def test_reads_branding_from_user_admin_custom_variables(as_dicts):
    variables = cv(
        melorin_brand_name="فروشگاه من", melorin_support_url="https://t.me/shop", melorin_logo_url="https://cdn.example/l.png", theme="dark"
    )
    html = _render(variables, as_dicts=as_dicts)
    assert "فروشگاه من" in html and 'href="https://t.me/shop"' in html and 'src="https://cdn.example/l.png"' in html


def test_the_old_top_level_names_are_not_a_source():
    """Regression: the first version read ``admin`` / ``custom_variables`` at top level, which the panel never provides."""
    html = _render(custom_variables={"melorin_brand_name": "X"}, admin=NS(custom_variables={"MELORIN_BRAND_NAME": "X"}))
    assert "اشتراک شما" in html and ">X<" not in html


def test_values_are_escaped_and_unsafe_links_dropped():
    html = _render(
        cv(melorin_brand_name="<script>alert(1)</script>", melorin_support_url="javascript:alert(1)", melorin_logo_url="http://x/l.png")
    )
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert "javascript:" not in html and "<img" not in html


def test_no_script_and_no_external_requests():
    html = _render()
    assert "<script" not in html and "default-src 'none'" in html
