#!/usr/bin/env bash
# S103 - rotate secrets that a leaked GitHub token could have reached. Operator-run, never in CI.
# Subcommands (no secret is ever printed except the PUBLIC key):
#   gen-deploy-key <dir>            new ed25519 deploy key pair in <dir> (private key mode 600)
#   verify-key <key> <user@host> [port]   prints OK if the server ACCEPTS the key
#   verify-rejected <key> <user@host> [port]   prints OK if the server REJECTS the key (use for the OLD key)
#   gen-app-secrets <outfile>       fresh random values for app secrets (file mode 600, apply by hand)
#   audit-authorized-keys           run ON the server: list keys in authorized_keys with fingerprints
set -Eeuo pipefail
umask 077
cmd="${1:-}"; shift || true
ssh_try() { # key target port -> exit code of a no-op ssh using only that key
  ssh -i "$1" -p "${3:-22}" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=10 \
      -o StrictHostKeyChecking=yes "$2" true >/dev/null 2>&1
}
case "$cmd" in
  gen-deploy-key)
    dir="${1:?dir}"; mkdir -p "$dir"
    stamp="$(date -u +%Y%m%d)"
    ssh-keygen -t ed25519 -N '' -C "melorin-deploy-$stamp" -f "$dir/id_deploy_$stamp" >/dev/null
    echo "private: $dir/id_deploy_$stamp  (store as GitHub secret DEPLOY_SSH_KEY, then shred the file)"
    echo "public key (append to server ~/.ssh/authorized_keys):"; cat "$dir/id_deploy_$stamp.pub" ;;
  verify-key)
    ssh_try "${1:?key}" "${2:?user@host}" "${3:-22}" && echo "OK: server accepts key" || { echo "FAIL: key not accepted" >&2; exit 1; } ;;
  verify-rejected)
    if ssh_try "${1:?key}" "${2:?user@host}" "${3:-22}"; then echo "FAIL: old key still accepted" >&2; exit 1; else echo "OK: key rejected"; fi ;;
  gen-app-secrets)
    out="${1:?outfile}"; [[ ! -e "$out" ]] || { echo "refusing to overwrite $out" >&2; exit 2; }
    r() { python3 -c 'import secrets;print(secrets.token_urlsafe(48))'; }
    {
      echo "MELORIN_JWT_SECRET=$(r)"
      echo "MELORIN_BOT_SERVICE_SECRET=$(r)"
      echo "MELORIN_MAIN_BOT_SECRET=$(r)"
      echo "MELORIN_RESELLER_BOT_SECRET=$(r)"
      echo "MELORIN_METRICS_TOKEN=$(r)"
      echo "MELORIN_HEALTH_TOKEN=$(r)"
      echo "NEW_FERNET_KEY=$(python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
    } > "$out"; chmod 600 "$out"; echo "written: $out (mode 600). Apply per docs/security/S103-secret-rotation.md" ;;
  audit-authorized-keys)
    f="${HOME}/.ssh/authorized_keys"; [[ -r "$f" ]] || { echo "no $f" >&2; exit 2; }
    while IFS= read -r line; do
      [[ -z "$line" || "$line" == \#* ]] && continue
      printf '%s\n' "$line" | ssh-keygen -lf - 2>/dev/null || echo "UNPARSEABLE LINE"
    done < "$f" ;;
  *) sed -n 2,9p "$0"; exit 64 ;;
esac
