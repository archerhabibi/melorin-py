#!/usr/bin/env bash
set -euo pipefail
# Review source/config only; ignore examples that intentionally use placeholders.
! grep -RInE --exclude-dir=.git --exclude-dir=__pycache__ --exclude='*.pyc' --exclude='.env.example' \
  '(sk_(live|test)_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,}|[0-9]{9,10}:[A-Za-z0-9_-]{30,}|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|password[[:space:]]*=[[:space:]]*["\x27][^"\x27]{8,}["\x27]|secret[[:space:]]*=[[:space:]]*["\x27][^"\x27]{8,}["\x27])' .
