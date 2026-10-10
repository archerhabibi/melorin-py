"""Small real HTTP integration checks.

The CI job supplies PostgreSQL/Redis and runs the complete E2E flow separately.
These checks prove the ASGI boundary itself and remain opt-in with the
integration marker so local unit runs never pretend to be runtime evidence.
"""
import httpx
import pytest
from pathlib import Path


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_health_over_asgi_transport():
    from melorin.app import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.integration
@pytest.mark.concurrency
def test_external_concurrency_smoke_is_declared():
    """The DB race test is intentionally executed as a script with real services."""
    script = Path(__file__).parents[2] / "scripts" / "postgres_concurrency_smoke.py"
    assert script.is_file()
