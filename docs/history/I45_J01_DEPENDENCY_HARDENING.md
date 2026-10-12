# I45: J01 Dependency Hardening

J01 reported vulnerable pins in the API dependency set. The runtime and test
pins are now upgraded together:

- FastAPI `0.143.0` (brings the compatible Starlette release line)
- PyJWT `2.15.0`
- cryptography `50.0.0`
- python-multipart `0.0.32`
- pytest `9.1.1`, pytest-asyncio `1.4.0`, pytest-cov `7.1.0`

`requirements.txt` and `pyproject.toml` intentionally carry the same direct
dependency versions. CI now installs pinned `pip-audit 2.10.1` and fails the
quality job when the resolved requirements contain known vulnerabilities.
Dependabot is enabled for the API and both web applications so future fixes
arrive as reviewable pull requests rather than silent drift.

The audit still needs to be executed in a package-registry-enabled CI runner;
the local sandbox has no package registry access.
