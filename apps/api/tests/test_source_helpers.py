"""M6.7: contract tests that read source must survive re-formatting."""

from _source import normalize_source


def test_wrapping_and_trailing_commas_do_not_change_normalised_source():
    compact = 'call(a, b, key="v")\nITEMS = [1, 2]\n'
    wrapped = 'call(\n    a,\n    b,\n    key="v",\n)\nITEMS = [\n    1,\n    2,\n]\n'
    assert normalize_source(compact) == normalize_source(wrapped)


def test_real_changes_are_still_detected():
    assert normalize_source("x = f(a)") != normalize_source("x = f(b)")
    assert "with_for_update=True" not in normalize_source("session.get(Model, 1)")
