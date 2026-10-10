import ast
from pathlib import Path


def test_telegram_runners_are_real_and_persistent():
    main = Path(__file__).parents[2].joinpath("telegram-main", "runner.py")
    reseller = Path(__file__).parents[2].joinpath("telegram-reseller", "runner.py")
    main_source = main.read_text()
    ast.parse(main_source)
    ast.parse(reseller.read_text())
    for marker in ("getUpdates", "auth/telegram/bot", "offset_file", "callback_query", "sendMessage"):
        assert marker in main_source
