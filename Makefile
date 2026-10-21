.PHONY: docs restore-drill-latest deploy-test evidence guards up down logs migrate migration-smoke integration-smoke restore-drill test-matrix revision test lint api worker install-verify quality-gate
install-verify:
	@bash scripts/install_verify.sh
guards:
	@python scripts/check_g001_g010.py && python scripts/check_quality_config.py && python scripts/check_ops_p0.py && python scripts/gen_docs.py --check
docs:
	@python scripts/gen_docs.py
quality-gate:
	@bash scripts/run_quality_gate.sh
migration-smoke:
	@bash scripts/migration_smoke.sh
integration-smoke:
	@bash scripts/integration_smoke.sh
evidence:
	@python scripts/runtime_evidence.py --allow-mutation
restore-drill:
	@bash scripts/backup_restore_drill.sh
restore-drill-latest:
	@bash scripts/restore_drill_latest.sh
deploy-test:
	@bash scripts/test_deploy.sh && bash scripts/test_restore_drill.sh
test-matrix:
	@python scripts/test_matrix.py all
up:; cp -n .env.example .env || true; docker compose up -d --build
down:; docker compose down
logs:; docker compose logs -f api worker
migrate:; docker compose run --rm api alembic upgrade head
revision:; docker compose run --rm api alembic revision --autogenerate -m "schema"
test:; cd apps/api && pytest -q
lint:; cd apps/api && lint-imports && ruff check melorin --config pyproject.toml && ruff format --check melorin tests --config pyproject.toml
api:; cd apps/api && uvicorn melorin.app:app --reload
worker:; cd apps/api && arq melorin.worker.arq_app.WorkerSettings

setup-git:; git config commit.template .gitmessage && echo 'commit template enabled (optional trailers fill docs/CHANGE_LOG.md)'
