"""Test-only path setup for the Telegram bot suite.

A few tests (e.g. ``test_token_redaction_and_429``) deliberately import ``melorin.core`` to prove that the bot's token
redaction pattern has not drifted from the Core's. The bot *image* never imports Core, so this must not leak into
production code: the path is added here, at the end of ``sys.path`` (bot modules keep priority), and only for tests.

Without it the suite only passed when pytest happened to be started with ``apps/api`` on the path
(``python -m pytest`` or ``PYTHONPATH=.``); the plain ``pytest -q ../telegram-main/tests`` invocation used by CI failed
with ``ModuleNotFoundError: melorin``.
"""

import sys
from pathlib import Path

_API_ROOT = str(Path(__file__).resolve().parents[2] / "api")
if _API_ROOT not in sys.path:
    sys.path.append(_API_ROOT)
