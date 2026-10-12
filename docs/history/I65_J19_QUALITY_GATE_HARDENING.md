# I65: J19 Quality Gate Hardening

The lint gate now checks more than undefined names and syntax-adjacent errors:
Ruff import sorting (`I`), pyupgrade rules (`UP`), and bugbear checks (`B`) are
enabled alongside the existing correctness rules. Ruff's formatter policy is
declared in `pyproject.toml`.

The local quality script, Make target, and GitHub Actions all run both
`ruff check` and `ruff format --check`. `scripts/check_quality_config.py`
provides a small consistency guard so those entrypoints cannot silently drift
apart.
