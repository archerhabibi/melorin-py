import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]


def squash(text: str) -> str:
    """Whitespace- and quote-insensitive form, so Prettier/formatting changes never break the contracts."""
    return re.sub(r"\s+", "", text).replace("'", '"')


def has(needle: str, text: str) -> bool:
    return squash(needle) in squash(text)


store = (root / "apps/store-web/src/App.jsx").read_text()
admin = (root / "apps/admin-web/src/App.jsx").read_text()
caddy = (root / "infra/Caddyfile").read_text()
api = (root / "apps/api/melorin/app.py").read_text()
checks = {
    "Store ID is declared": has("const [storeId, setStoreId]", store),
    "Store ID is resolved": has("setStoreId(store.id)", store),
    "Orders are Store-scoped": has("coreFetch(`/api/v1/stores/${storeId}/orders`).then", store),
    "No unscoped order collection": not has('coreFetch("/api/v1/orders")', store),
    "Admin ticket badge is defined": has("{openTickets}</span>", admin) and not has("{tickets}</span>", admin),
    "Admin section tables are mounted": has("<AdminSectionView section={section} api={api} toast={toast}/>", admin),
    "Demo fallback is not rendered": (has("catalog.length ? catalog.map", store) or (has("catalog.length ? (", store) and has("catalog.map(", store)))
    and not has("catalog.length ? catalog : demoPlans", store),
    "Proxy health paths exist": "/health/*" in caddy and "/health " in caddy,
    "Health compatibility endpoint exists": '@app.get("/healthz"' in api,
}
failed = [k for k, v in checks.items() if not v]
if failed:
    raise SystemExit("frontend/integration contract failures: " + ", ".join(failed))
print(f"frontend/integration contracts passed ({len(checks)})")
