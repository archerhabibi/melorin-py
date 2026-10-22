"""M6.7: contract tests that read source must survive re-formatting."""

from pathlib import Path

from _source import normalize_source


def test_wrapping_and_trailing_commas_do_not_change_normalised_source():
    compact = 'call(a, b, key="v")\nITEMS = [1, 2]\n'
    wrapped = 'call(\n    a,\n    b,\n    key="v",\n)\nITEMS = [\n    1,\n    2,\n]\n'
    assert normalize_source(compact) == normalize_source(wrapped)


def test_real_changes_are_still_detected():
    assert normalize_source("x = f(a)") != normalize_source("x = f(b)")
    assert "with_for_update=True" not in normalize_source("session.get(Model, 1)")


def test_web_source_is_stable_under_prettier_layout():
    from _source import normalize_web_source

    before = "const x = {\n  'a b': f('x', { k: 1 }),\n};\n"
    after = 'const x = {"a b": f("x", {k: 1})};'
    assert normalize_web_source(before) == normalize_web_source(after)
    assert normalize_web_source("f('a')") != normalize_web_source("f('b')")


def test_dialog_hook_is_identical_in_both_web_apps():
    """Phase 6.4: one overlay behaviour (focus trap, Esc on the topmost dialog) shared byte-for-byte."""
    apps = Path(__file__).resolve().parents[2]
    admin = (apps / "admin-web/src/useDialog.js").read_bytes()
    store = (apps / "store-web/src/useDialog.js").read_bytes()
    assert admin == store
