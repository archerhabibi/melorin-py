from pathlib import Path
root=Path(__file__).resolve().parents[1]
store=(root/"apps/store-web/src/App.jsx").read_text()
admin=(root/"apps/admin-web/src/App.jsx").read_text()
caddy=(root/"infra/Caddyfile").read_text()
api=(root/"apps/api/melorin/app.py").read_text()
checks={
"Store ID is declared": "const [storeId, setStoreId]" in store,
"Store ID is resolved": "setStoreId(store.id)" in store,
"Orders are Store-scoped": "coreFetch(`/api/v1/stores/${storeId}/orders`).then" in store,
"No unscoped order collection": 'coreFetch("/api/v1/orders")' not in store,
"Admin ticket badge is defined": "{openTickets}</span>" in admin and "{tickets}</span>" not in admin,
"Admin section tables are mounted": "<AdminSectionView section={section} api={api} toast={toast}/>" in admin,
"Demo fallback is not rendered": "catalog.length ? catalog.map" in store and "catalog.length ? catalog : demoPlans" not in store,
"Proxy health paths exist": "/health/*" in caddy and "/health " in caddy,
"Health compatibility endpoint exists": '@app.get("/healthz"' in api,
}
failed=[k for k,v in checks.items() if not v]
if failed: raise SystemExit("frontend/integration contract failures: "+", ".join(failed))
print(f"frontend/integration contracts passed ({len(checks)})")
