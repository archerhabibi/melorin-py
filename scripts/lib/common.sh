# shellcheck shell=bash
# shellcheck disable=SC1091  # /etc/os-release is sourced on purpose
# Shared helpers for Melorin's server scripts (melorin.sh, scripts/install_server.sh).
# SOURCE this file, never run it. get.sh cannot use it (it runs before the repository exists) and carries its own
# small copies of retry / apt_run.
#
# Contents: terminal + retry + apt helpers, input validators, network probes, Docker bootstrap, failure hints and the
# preflight checks behind `melorin doctor` and the installer's "is this server fit" gate.
[ -n "${_MELORIN_COMMON:-}" ] && return 0
_MELORIN_COMMON=1

MELORIN_LOG_FILE="${MELORIN_LOG_FILE:-/var/log/melorin-install.log}"
MIN_COMPOSE_VERSION="2.20.0"
MIN_RAM_MIB_WARN=3500   # docker-compose.yml: the long-running services' memory caps add up to 3584 MiB
MIN_RAM_MIB_FAIL=1800
MIN_DISK_GB_WARN=15
MIN_DISK_GB_FAIL=8

# ---------------------------------------------------------------- terminal / retry / apt
# True when a controlling terminal can really be opened. /dev/tty always EXISTS (even for `ssh host cmd` without -t, cron,
# cloud-init), so `[ -r /dev/tty ]` is not a test: opening it is.
has_tty() { ( : </dev/tty ) 2>/dev/null; }

retry() { # retry TRIES DELAY cmd...   (the delay doubles after every failure; returns the last failure)
  # _r_* names: bash scopes `local` dynamically, so a retried function that uses a variable called n/delay/tries would otherwise
  # change the counters of retry itself.
  local _r_tries="$1" _r_delay="$2" _r_n=1 _r_what; shift 2
  _r_what="$*"
  until "$@"; do
    if [ "$_r_n" -ge "$_r_tries" ]; then return 1; fi
    printf ' !! attempt %s/%s failed: %s (retrying in %ss)\n' "$_r_n" "$_r_tries" "${_r_what:0:90}" "$_r_delay" >&2
    sleep "$_r_delay"; _r_n=$((_r_n + 1)); _r_delay=$((_r_delay * 2))
  done
}

# apt that survives a fresh server: waits for the dpkg lock (unattended-upgrades / cloud-init hold it for minutes on first
# boot), never opens a dialog (debconf, and needrestart's TUI on Ubuntu 22.04+ which would hang an unattended run).
apt_run() {
  DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l NEEDRESTART_SUSPEND=1 \
    apt-get -o DPkg::Lock::Timeout=300 -o Acquire::Retries=3 \
            -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold "$@"
}
apt_install() { # apt_install pkg...   (one `apt-get update` per run; flaky mirrors and the apt lists lock are retried)
  if [ -z "${_APT_UPDATED:-}" ]; then
    retry 4 5 apt_run update -qq || return 1
    _APT_UPDATED=1
  fi
  retry 3 5 apt_run install -y -qq --no-install-recommends "$@"
}

ver_ge() { [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n1)" = "$2" ]; } # ver_ge A B  <=>  A >= B

# ---------------------------------------------------------------- validators
norm_domain() { # strip spaces, scheme, path and a trailing dot; lowercase
  local d="${1,,}"; d="${d//[[:space:]]/}"; d="${d#http://}"; d="${d#https://}"; d="${d%%/*}"; d="${d%.}"; printf '%s' "$d"
}
valid_domain() {
  [ "${#1}" -le 253 ] || return 1
  [[ "$1" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+([a-z]{2,}|xn--[a-z0-9-]{2,})$ ]]
}
valid_token() { [[ "$1" =~ ^[0-9]+:[A-Za-z0-9_-]{30,}$ ]]; }

# V-004: the application's login validator (email-validator) rejects special-use domains; refuse them here too, otherwise the
# admin account is created and can never sign in (HTTP 422 on every login).
valid_email() {
  [[ "$1" =~ ^[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$ ]] || return 1
  local d="${1#*@}"
  case "$d" in
    *.test|*.local|*.localhost|*.invalid|*.onion|*.arpa|test|local|localhost|invalid) return 1 ;;
  esac
  return 0
}

# ---------------------------------------------------------------- network probes
server_ip() { # public IPv4 of this host (first answer wins); prints nothing and fails when every probe is blocked
  local u ip
  for u in https://api.ipify.org https://ifconfig.me https://ipv4.icanhazip.com; do
    ip="$(curl -4 -fsS -m 6 "$u" 2>/dev/null | tr -d '[:space:]')" || ip=""
    if [[ "$ip" =~ ^[0-9]+(\.[0-9]+){3}$ ]]; then printf '%s' "$ip"; return 0; fi
  done
  return 1
}
domain_ip() { getent ahostsv4 "$1" 2>/dev/null | awk '{print $1; exit}'; }

# Who listens on TCP port $1? Prints "name (pid N)" and succeeds; fails (prints nothing) when the port is free.
port_owner() {
  local line owner
  line="$(ss -H -ltnp 2>/dev/null | awk -v p="$1" '{ n = split($4, a, ":"); if (a[n] == p) { print; exit } }')"
  [ -n "$line" ] || return 1
  owner="$(printf '%s' "$line" | sed -n 's/.*users:(("\([^"]*\)",pid=\([0-9]*\).*/\1 (pid \2)/p')"
  printf '%s' "${owner:-another process}"
}
port_busy() { port_owner "$1" >/dev/null; }

# Anything that answers over HTTPS proves the route works; 401/403/404 are fine, a timeout or reset is not.
reach() { # reach URL
  local code
  code="$(curl -sS -m 10 -o /dev/null -w '%{http_code}' "$1" 2>/dev/null)" || return 1
  [ "$code" != 000 ]
}

# ---------------------------------------------------------------- Docker
docker_compose_version() { docker compose version --short 2>/dev/null | head -n1 | sed 's/^v//'; }

install_docker_engine() { # official apt repository first (signed, current); the distribution packages as a fallback
  local id codename arch
  id="$(. /etc/os-release && printf '%s' "${ID:-}")"
  codename="$(. /etc/os-release && printf '%s' "${VERSION_CODENAME:-}")"
  arch="$(dpkg --print-architecture)"
  case "$id" in ubuntu|debian) ;; *) id="" ;; esac
  if [ -n "$id" ] && [ -n "$codename" ]; then
    echo ">> Installing Docker Engine + Compose plugin from the official Docker apt repository"
    if apt_install ca-certificates curl gnupg \
       && install -m 0755 -d /etc/apt/keyrings \
       && retry 3 5 curl -fsSL "https://download.docker.com/linux/${id}/gpg" -o /etc/apt/keyrings/docker.asc \
       && chmod a+r /etc/apt/keyrings/docker.asc \
       && printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
            "$arch" "$id" "$codename" > /etc/apt/sources.list.d/docker.list \
       && { _APT_UPDATED=""; apt_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; }; then
      return 0
    fi
    echo "!! The official Docker repository did not work; trying the distribution packages" >&2
    rm -f /etc/apt/sources.list.d/docker.list
    _APT_UPDATED=""
  fi
  apt_install docker.io && { apt_install docker-compose-v2 || apt_install docker-compose-plugin; }
}

# Make sure `docker compose` (v2, new enough) talks to a running daemon. Installs what is missing. Idempotent.
ensure_docker() {
  local v i
  if ! command -v docker >/dev/null 2>&1; then
    install_docker_engine || { echo "!! Docker could not be installed (see above). Install Docker Engine + the Compose v2 plugin by hand, then run again." >&2; return 1; }
  fi
  if ! docker compose version >/dev/null 2>&1; then
    echo ">> Docker is installed but the Compose v2 plugin is missing; installing it"
    apt_install docker-compose-plugin || apt_install docker-compose-v2 \
      || { echo "!! The Docker Compose v2 plugin could not be installed (docker.io + docker-compose v1 is not enough)." >&2; return 1; }
  fi
  if ! docker info >/dev/null 2>&1; then
    systemctl enable --now docker >/dev/null 2>&1 || service docker start >/dev/null 2>&1 || true
    # shellcheck disable=SC2034  # i only counts the seconds
    for i in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "!! The Docker daemon is not running. Look at: systemctl status docker ; journalctl -u docker --no-pager | tail -30" >&2
    return 1
  fi
  v="$(docker_compose_version)"
  if [ -z "$v" ] || ! ver_ge "$v" "$MIN_COMPOSE_VERSION"; then
    echo "!! Docker Compose ${v:-unknown} is older than $MIN_COMPOSE_VERSION. Update the docker-compose-plugin package." >&2
    return 1
  fi
}

# transient_failure LOGFILE -> 0 when the log looks like a flaky network, i.e. when trying again can help.
transient_failure() {
  grep -qiE 'i/o timeout|TLS handshake timeout|Temporary failure in name resolution|connection reset|unexpected EOF|received unexpected HTTP status: 50[234]|503 Service Unavailable|failed to do request|dial tcp.*(timeout|refused)' "$1" 2>/dev/null
}

# docker_failure_hint LOGFILE -> prints the most likely cause and the fix for a failed pull/build. Returns 0 when it knew one.
docker_failure_hint() {
  local f="$1" hit=1
  _hint() { if grep -qiE "$1" "$f" 2>/dev/null; then printf ' >> %s\n' "$2" >&2; hit=0; fi; }
  _hint 'toomanyrequests|pull rate limit' "Docker Hub rate limit: run 'docker login' (a free account is enough) or wait an hour, then run the same command again."
  _hint '403 Forbidden|denied: |unauthorized: ' "The registry refused this server (geo/sanction block or login required). Put a registry mirror in /etc/docker/daemon.json (\"registry-mirrors\") or route the server through a proxy, then run again."
  _hint 'i/o timeout|TLS handshake timeout|Temporary failure in name resolution|no such host|network is unreachable|connection refused' "Network problem while downloading: check DNS (/etc/resolv.conf), the firewall and outbound HTTPS, then run again."
  _hint 'no space left on device' "The disk is full: free space (df -h ; docker system prune -af) and run again."
  _hint 'signal: killed|exit code: 137|out of memory|Cannot allocate memory' "The build ran out of memory: add swap (SWAP_GB=4 bash scripts/post_install.sh) or use a 4 GB server, then run again."
  unset -f _hint
  return "$hit"
}

# ---------------------------------------------------------------- preflight (installer gate + `melorin doctor`)
if [ -t 1 ]; then PF_G=$'\033[32m'; PF_Y=$'\033[33m'; PF_R=$'\033[31m'; PF_0=$'\033[0m'; else PF_G=""; PF_Y=""; PF_R=""; PF_0=""; fi
PF_FAIL=0; PF_WARN=0
pf_ok()   { printf '  %s[ ok ]%s %s\n' "$PF_G" "$PF_0" "$*"; }
pf_warn() { printf '  %s[warn]%s %s\n' "$PF_Y" "$PF_0" "$*"; PF_WARN=$((PF_WARN + 1)); }
pf_fail() { printf '  %s[FAIL]%s %s\n' "$PF_R" "$PF_0" "$*"; PF_FAIL=$((PF_FAIL + 1)); }
pf_hard() { # a failure that MELORIN_FORCE=1 (--force) downgrades to a warning
  if [ "${MELORIN_FORCE:-0}" = 1 ]; then pf_warn "$* (ignored: --force)"; else pf_fail "$*"; fi
}

preflight_system() {
  local id ver pretty arch ram swap free virt
  id="$(. /etc/os-release 2>/dev/null && printf '%s' "${ID:-}")"
  ver="$(. /etc/os-release 2>/dev/null && printf '%s' "${VERSION_ID:-}")"
  pretty="$(. /etc/os-release 2>/dev/null && printf '%s' "${PRETTY_NAME:-unknown}")"
  arch="$(dpkg --print-architecture 2>/dev/null || uname -m)"

  case "$id" in
    ubuntu) if ver_ge "${ver:-0}" 22.04; then pf_ok "OS: $pretty"; else pf_hard "OS: $pretty is too old (Ubuntu 22.04 or newer)"; fi ;;
    debian) if [ -z "$ver" ] || ver_ge "$ver" 12; then pf_ok "OS: $pretty"; else pf_hard "OS: $pretty is too old (Debian 12 or newer)"; fi ;;
    *)      pf_warn "OS: $pretty is untested (supported: Ubuntu 22.04+, Debian 12+)" ;;
  esac
  case "$arch" in
    amd64|x86_64|arm64|aarch64) pf_ok "CPU architecture: $arch" ;;
    *) pf_hard "CPU architecture $arch is not supported (amd64 / arm64)" ;;
  esac

  ram="$(awk '/^MemTotal:/ {print int($2/1024)}' /proc/meminfo 2>/dev/null)"; ram="${ram:-0}"
  swap="$(awk '/^SwapTotal:/ {print int($2/1024)}' /proc/meminfo 2>/dev/null)"; swap="${swap:-0}"
  if [ "$ram" -lt "$MIN_RAM_MIB_FAIL" ]; then
    pf_hard "RAM: ${ram} MiB is too little (the stack needs about 3.5 GiB; 4 GB server recommended)"
  elif [ "$ram" -lt "$MIN_RAM_MIB_WARN" ]; then
    pf_warn "RAM: ${ram} MiB (+${swap} MiB swap); the stack is budgeted for 3584 MiB, so it will lean on swap. A 4 GB server is recommended"
  else
    pf_ok "RAM: ${ram} MiB (+${swap} MiB swap)"
  fi

  free="$(df -BG --output=avail / 2>/dev/null | tail -n1 | tr -dc '0-9')"; free="${free:-0}"
  if [ "$free" -lt "$MIN_DISK_GB_FAIL" ]; then pf_hard "Disk: only ${free} GB free on / (images + database need ${MIN_DISK_GB_WARN}+ GB)"
  elif [ "$free" -lt "$MIN_DISK_GB_WARN" ]; then pf_warn "Disk: ${free} GB free on / (${MIN_DISK_GB_WARN}+ GB recommended)"
  else pf_ok "Disk: ${free} GB free on /"; fi

  virt="$(systemd-detect-virt 2>/dev/null || true)"
  case "$virt" in
    openvz) pf_hard "Virtualization: OpenVZ cannot run Docker; use a KVM/Xen VPS" ;;
    lxc|lxc-libvirt|docker|podman) pf_warn "Virtualization: running inside a container ($virt); Docker may need nesting enabled" ;;
    ""|none) pf_ok "Virtualization: ${virt:-none/unknown}" ;;
    *) pf_ok "Virtualization: $virt" ;;
  esac
}

preflight_docker() {
  local v dbin
  if ! command -v docker >/dev/null 2>&1; then pf_warn "Docker is not installed (the installer will install it)"; return 0; fi
  dbin="$(readlink -f "$(command -v docker)")"
  case "$dbin" in /snap/*) pf_warn "Docker comes from snap ($dbin); bind mounts under /opt are restricted there. Prefer the apt package" ;; esac
  if ! docker compose version >/dev/null 2>&1; then pf_fail "Docker Compose v2 plugin is missing (the installer will install it)"; return 0; fi
  v="$(docker_compose_version)"
  if [ -n "$v" ] && ver_ge "$v" "$MIN_COMPOSE_VERSION"; then pf_ok "Docker Compose $v"; else pf_fail "Docker Compose ${v:-unknown} is older than $MIN_COMPOSE_VERSION"; fi
  if docker info >/dev/null 2>&1; then pf_ok "Docker daemon is running"; else pf_fail "Docker daemon is not running (systemctl start docker)"; fi
}

preflight_network() {
  if reach https://github.com; then pf_ok "github.com reachable"; else pf_fail "github.com is unreachable (needed to download and update Melorin)"; fi
  if reach https://registry-1.docker.io/v2/; then pf_ok "Docker Hub reachable"
  else pf_warn "Docker Hub is unreachable: image builds will fail unless a registry mirror is configured (/etc/docker/daemon.json)"; fi
  if ! command -v docker >/dev/null 2>&1; then
    if reach https://download.docker.com; then pf_ok "download.docker.com reachable"; else pf_warn "download.docker.com is unreachable: Docker would have to come from the distribution packages"; fi
  fi
  if reach https://api.telegram.org; then pf_ok "api.telegram.org reachable"
  else pf_warn "api.telegram.org is unreachable from this server: the Telegram bots and alerts cannot work from here"; fi
  if [ "${EXTERNAL_PROXY:-false}" != true ]; then
    if reach https://acme-v02.api.letsencrypt.org/directory; then pf_ok "Let's Encrypt reachable (TLS certificates)"
    else pf_warn "Let's Encrypt is unreachable: the bundled Caddy cannot issue TLS certificates"; fi
  fi
}

preflight_ports() {
  local p owner
  for p in 80 443; do
    if owner="$(port_owner "$p")"; then
      pf_fail "Port $p is in use by $owner. Stop it, or install with --external-proxy and route your own proxy to Melorin"
    else
      pf_ok "Port $p is free"
    fi
  done
}

preflight_dns() { # preflight_dns domain...   (informational: Cloudflare-style proxies legitimately differ)
  local sip d dip
  sip="$(server_ip || true)"
  if [ -z "$sip" ]; then pf_warn "DNS: could not detect this server's public IP; skipped"; return 0; fi
  for d in "$@"; do
    dip="$(domain_ip "$d")"
    if [ "$dip" = "$sip" ]; then pf_ok "DNS: $d -> $dip"; else pf_warn "DNS: $d resolves to '${dip:-nothing}', this server is $sip"; fi
  done
}
