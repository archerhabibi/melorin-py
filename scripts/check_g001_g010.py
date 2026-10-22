import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]


def squash(text: str) -> str:
    """Whitespace- and quote-insensitive form, so Prettier/formatting changes never break the guards."""
    return re.sub(r"\s+", "", text).replace("'", '"')


def has(needle: str, text: str) -> bool:
    return squash(needle) in squash(text)


store = (root / "apps/store-web/src/App.jsx").read_text()
admin = (root / "apps/admin-web/src/App.jsx").read_text()
caddy = (root / "infra/Caddyfile").read_text()
api = (root / "apps/api/melorin/app.py").read_text()
base = (root / "apps/api/alembic/versions/0001_initial.py").read_text()
req = (root / "apps/api/requirements-dev.txt").read_text()
checks = {
    "G001": has("const [storeId, setStoreId]", store) and has("setStoreId(store.id)", store),
    "G002": has("{openTickets}</span>", admin) and not has("{tickets}</span>", admin),
    "G003": has("<AdminSectionView section={section} api={api} toast={toast}/>", admin),
    "G004": has("coreFetch(`/api/v1/stores/${storeId}/orders`).then", store),
    "G005": "/health/*" in caddy and '@app.get("/healthz"' in api,
    "G006": "pytest==" in req and "ruff==" in req,
    "G007": (root / "scripts/preflight.py").is_file(),
    "G008": (has("catalog.length ? catalog.map", store) or (has("catalog.length ? (", store) and has("catalog.map(", store))) and not has("catalog.length ? catalog : demoPlans", store),
    "G009": (root / "scripts/check_frontend_contracts.py").is_file(),
    "G010": "drop_all" not in base and "create_all" not in base,
}
failed = [k for k, v in checks.items() if not v]
if failed:
    raise SystemExit("failed: " + ", ".join(failed))
print("G001-G010 checks passed (10)")
