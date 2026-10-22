from pathlib import Path
root=Path(__file__).resolve().parents[1]
store=(root/'apps/store-web/src/App.jsx').read_text(); admin=(root/'apps/admin-web/src/App.jsx').read_text(); caddy=(root/'infra/Caddyfile').read_text(); api=(root/'apps/api/melorin/app.py').read_text(); base=(root/'apps/api/alembic/versions/0001_initial.py').read_text(); req=(root/'apps/api/requirements-dev.txt').read_text()
checks={'G001':'const [storeId, setStoreId]' in store and 'setStoreId(store.id)' in store,'G002':'{openTickets}</span>' in admin and '{tickets}</span>' not in admin,'G003':'<AdminSectionView section={section} api={api} toast={toast}/>' in admin,'G004':'coreFetch(`/api/v1/stores/${storeId}/orders`).then' in store,'G005':'/health/*' in caddy and '@app.get("/healthz"' in api,'G006':'pytest==' in req and 'ruff==' in req,'G007':(root/'scripts/preflight.py').is_file(),'G008':'catalog.length ? catalog.map' in store and 'catalog.length ? catalog : demoPlans' not in store,'G009':(root/'scripts/check_frontend_contracts.py').is_file(),'G010':'drop_all' not in base and 'create_all' not in base}
failed=[k for k,v in checks.items() if not v]
if failed: raise SystemExit('failed: '+', '.join(failed))
print('G001-G010 checks passed (10)')
