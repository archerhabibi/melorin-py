#!/usr/bin/env bash
# Host hardening for the shared Melorin VPS (audit P0 / P9: T28 firewall, T25 swap, T32 plaintext dumps, T33/T17 clutter).
#
#   scripts/harden_host.sh              # DRY RUN: prints what it would do, changes nothing
#   scripts/harden_host.sh --apply      # do it
#
# Environment (all optional):
#   SSH_PORT          port sshd listens on            (default: detected from `ss`, else 22)
#   EXTRA_TCP         space-separated ports to open to everyone   (default: none)
#   NODE_IPS          space-separated PasarGuard node IPs allowed to reach PANEL_NODE_PORTS
#   PANEL_NODE_PORTS  default "62050 62051"
#   SWAP_GB           swap file size in GiB, 0 = skip  (default 2)
#   BACKUP_DIR        where plaintext *.sql dumps live  (default /root/backups)
#   AGE_RECIPIENT     age public key; when set, plaintext dumps are encrypted with it and the original shredded
#
# It never touches Docker, never restarts a service and never closes the SSH port it detected.
set -euo pipefail

APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1
SSH_PORT="${SSH_PORT:-$( (ss -tlnp 2>/dev/null | awk '/sshd/ {n=split($4,a,":"); print a[n]; exit}') || true)}"
SSH_PORT="${SSH_PORT:-22}"
EXTRA_TCP="${EXTRA_TCP:-}"
NODE_IPS="${NODE_IPS:-}"
PANEL_NODE_PORTS="${PANEL_NODE_PORTS:-62050 62051}"
SWAP_GB="${SWAP_GB:-2}"
BACKUP_DIR="${BACKUP_DIR:-/root/backups}"

say() { printf '>> %s\n' "$*"; }
run() { if ((APPLY)); then say "RUN: $*"; "$@"; else say "DRY: $*"; fi; }

[[ $EUID -eq 0 ]] || { echo "run as root (sudo)"; exit 1; }
((APPLY)) || say "dry run - nothing will change. Re-run with --apply."

# ---- T28: firewall -----------------------------------------------------------------------------------------------
if command -v ufw >/dev/null 2>&1; then
  say "ufw status: $(ufw status | head -1)"
  say "SSH port detected: ${SSH_PORT} (it is allowed BEFORE the firewall is enabled)"
  run ufw default deny incoming
  run ufw default allow outgoing
  run ufw allow "${SSH_PORT}/tcp"
  run ufw allow 80/tcp
  run ufw allow 443/tcp
  for p in ${EXTRA_TCP}; do run ufw allow "${p}/tcp"; done
  if [[ -n "${NODE_IPS}" ]]; then
    for ip in ${NODE_IPS}; do for p in ${PANEL_NODE_PORTS}; do run ufw allow from "${ip}" to any port "${p}" proto tcp; done; done
  else
    say "NODE_IPS not set: ports ${PANEL_NODE_PORTS} will NOT be reachable from outside once ufw is on (fine if nodes run on this host)"
  fi
  # Docker publishes ports by editing iptables directly, so ufw alone does not hide a published container port.
  say "NOTE: containers must publish only 127.0.0.1:PORT (check: docker ps --format '{{.Names}} {{.Ports}}')"
  run ufw --force enable
else
  say "ufw is not installed: apt-get install -y ufw   (then re-run)"
fi

# ---- T28: what is listening on every interface -------------------------------------------------------------------
say "listeners on 0.0.0.0 / [::] (review each one):"
ss -tlnpH 2>/dev/null | awk '$4 ~ /^(0\.0\.0\.0|\[::\]|\*):/ {print "   " $4 "  " $6}' || true

# ---- T25: swap ---------------------------------------------------------------------------------------------------
if [[ "${SWAP_GB}" != "0" ]]; then
  if swapon --show --noheadings | grep -q .; then
    say "swap already active: $(swapon --show --noheadings | head -1)"
  else
    run fallocate -l "${SWAP_GB}G" /swapfile
    run chmod 600 /swapfile
    run mkswap /swapfile
    run swapon /swapfile
    if ! grep -q '^/swapfile ' /etc/fstab; then
      if ((APPLY)); then echo '/swapfile none swap sw 0 0' >>/etc/fstab; say "fstab entry added"; else say "DRY: add /swapfile to /etc/fstab"; fi
    fi
    run sysctl -w vm.swappiness=10
  fi
fi

# ---- T32: plaintext SQL dumps ------------------------------------------------------------------------------------
shopt -s nullglob
for f in "${BACKUP_DIR}"/*.sql; do
  if [[ -n "${AGE_RECIPIENT:-}" ]] && command -v age >/dev/null 2>&1; then
    run age -r "${AGE_RECIPIENT}" -o "${f}.age" "${f}"
    if ((APPLY)); then [[ -s "${f}.age" ]] && shred -u "${f}" && say "encrypted + shredded ${f}"; fi
  else
    say "plaintext dump: ${f} (set AGE_RECIPIENT and install age to encrypt it, or delete it after use)"
    run chmod 600 "${f}"
  fi
done

# ---- T33 / T17: clutter next to production (report only: never deleted automatically) -----------------------------
if [[ -d /opt/melorin/.git ]]; then
  say "untracked files in /opt/melorin (move them out; production should be a clean checkout):"
  git -C /opt/melorin status --porcelain --untracked-files=normal 2>/dev/null | sed 's/^/   /' || true
fi
for d in /root/melorin-py /root/work /root/venv-melorin; do [[ -e "$d" ]] && say "extra copy: $d ($(du -sh "$d" 2>/dev/null | cut -f1)) - archive patches, then remove"; done

say "done."
((APPLY)) || say "this was a dry run."
