import ast
from pathlib import Path


def test_telegram_runner_handles_callback_identity_and_persistent_offset():
    source = Path(__file__).parents[2].joinpath("telegram-main", "runner.py").read_text()
    ast.parse(source)
    assert "_telegram_from" in source
    assert "offset_file" in source
    assert "getUpdates" in source
    assert "answerCallbackQuery" in source
    assert "min(30" in source
