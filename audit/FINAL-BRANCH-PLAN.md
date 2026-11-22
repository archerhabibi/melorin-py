# FINAL-BRANCH-PLAN (Phase 0)

Decision by AI-00 after dependency analysis (`DEPENDENCY-MAP.md`).

## Order
The proposed chain in the execution plan is **kept**, with one adjustment: the audit phase (read-only) runs for all teams in parallel; the *fix* phase runs in chain order. Reasoning:
- Backend contract changes (AI-01) must precede security (AI-02) changes in the same files, and both precede DB/finance (AI-03) because AI-03 may regenerate the single Alembic baseline once all model changes are known.
- Integrations (AI-04) depend on payment/DB changes; frontends (AI-05) and bots (AI-06) consume the OpenAPI snapshot produced by AI-01…AI-04; DevOps (AI-07) and QA (AI-08) consume everything.

```
main
└── audit/00-baseline            (this PR: reports, tracker, no product code)
    └── audit/01-backend-core
        └── audit/02-security
            └── audit/03-database-finance
                └── audit/04-integrations
                    └── audit/05-frontend
                        └── audit/06-telegram-workers
                            └── audit/07-devops
                                └── audit/08-qa-performance
```

## Rules for this chain
- Each branch is created from its parent's head. Base SHA is recorded in the team report.
- PR N targets branch N-1 (`audit/00-baseline` targets `main`). Draft until checks are green.
- Generated files are regenerated, not hand-merged (see DEPENDENCY-MAP). The last commit of a team branch runs `make docs` and `python scripts/gen_api_client.py --write` if its change touched routes/schemas.
- A team with zero confirmed fixable findings still delivers its report PR (report-only), so the chain stays complete.
- The single Alembic baseline may be regenerated (project unreleased, owner approval 2026-11-22); AI-03 owns it. If a team needs a model change it asks AI-03.
- Breaking API/behaviour changes are allowed (owner statement 2026-11-22) but must be listed under "Compatibility" in the PR and have the OpenAPI/client regenerated.
- No `main` merge and no production deploy without the owner. There is currently no production.

## Phase gate
Phase 1 (audit) starts now for all teams in parallel and read-only. Phase 3 (fixes) starts team by team in chain order after AI-00 consolidates findings (BUG-REGISTRY.md).
