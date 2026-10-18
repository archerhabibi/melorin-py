import ast
from pathlib import Path

from _source import parse_source, read_source


def test_telegram_runner_handles_callback_identity_and_persistent_offset():
    runner = Path(__file__).parents[2].joinpath("telegram-main", "runner.py")
    source = read_source(runner)
    parse_source(runner)
    assert "_telegram_from" in source
    assert "offset_file" in source
    assert "getUpdates" in source
    assert "answerCallbackQuery" in source
    assert "min(30" in source
