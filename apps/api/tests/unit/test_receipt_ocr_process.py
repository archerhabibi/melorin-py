"""Cancellation and timeout must not leave OCR subprocesses running."""

import asyncio
import sys

import pytest

from melorin.modules.payments import receipt_ocr


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
async def test_stopped_ocr_terminates_and_reaps_its_subprocess(monkeypatch, stop):
    real_spawn = asyncio.create_subprocess_exec
    launched = asyncio.Event()
    children = []

    async def spawn(*args, **kwargs):
        process = await real_spawn(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
        children.append(process)
        launched.set()
        return process

    monkeypatch.setattr(receipt_ocr.asyncio, "create_subprocess_exec", spawn)
    config = receipt_ocr.OcrConfig("tesseract", "", "", "", 1 if stop == "timeout" else 60, "eng")
    task = asyncio.create_task(receipt_ocr._tesseract(b"receipt", config))
    try:
        await asyncio.wait_for(launched.wait(), timeout=10)
        if stop == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(TimeoutError):
                await task
        assert children[0].returncode is not None
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for process in children:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
