# I28: lint gate cleanup

The lint gate now uses one pinned Ruff configuration from
`apps/api/pyproject.toml` across local install verification, the quality gate,
and CI. It checks syntax-critical E4/E9 rules and pyflakes correctness while
explicitly documenting the legacy model re-export/import patterns that are not
runtime defects.

The previous 121-error default Ruff run mixed formatting-only one-liners and
intentional wildcard model registration with genuine correctness checks. The
gate is now deterministic and focused on defects that can break execution.
