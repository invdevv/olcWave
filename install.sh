#!/usr/bin/env bash
#
# install.sh - interactive installer for OLCWave.
#
# Asks you a handful of questions, then generates backend/.env
# (for Docker Compose) and frontend/.env for you, builds the frontend, and
# brings the Docker Compose stack up. No manual file editing required.
#
# Usage:
#   chmod +x install.sh
#   ./install.sh

set -euo pipefail

# Always operate from the repo root (the directory this script lives in).
cd "$(dirname "$0")"

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  C_RESET=$'\033[0m'; C_BLUE=$'\033[0;34m'; C_GREEN=$'\033[0;32m'
  C_YELLOW=$'\033[0;33m'; C_RED=$'\033[0;31m'; C_BOLD=$'\033[1m'
else
  C_RESET=''; C_BLUE=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_BOLD=''
fi

info()    { printf '%s[*]%s %s\n' "$C_BLUE"   "$C_RESET" "$1"; }
warn()    { printf '%s[!]%s %s\n' "$C_YELLOW" "$C_RESET" "$1"; }
success() { printf '%s[+]%s %s\n' "$C_GREEN"  "$C_RESET" "$1"; }
error()   { printf '%s[x]%s %s\n' "$C_RED"    "$C_RESET" "$1" >&2; }

# Fatal error: print and exit.
die() { error "$1"; exit 1; }

# ---------------------------------------------------------------------------
# Input helpers  (all read from /dev/tty so the script also works when piped)
# ---------------------------------------------------------------------------

# ask VAR "Prompt" ["default"]
# Reads a line into VAR. Falls back to the default when the input is empty.
ask() {
  local __var="$1" __msg="$2" __def="${3:-}" __in
  if [ -n "$__def" ]; then
    printf '%s%s%s [%s]: ' "$C_BOLD" "$__msg" "$C_RESET" "$__def" > /dev/tty
  else
    printf '%s%s%s: ' "$C_BOLD" "$__msg" "$C_RESET" > /dev/tty
  fi
  read -r __in < /dev/tty || true
  printf -v "$__var" '%s' "${__in:-$__def}"
}

# ask_required VAR "Prompt" - like ask, but keeps asking until non-empty.
ask_required() {
  local __var="$1" __msg="$2"
  while :; do
    ask "$__var" "$__msg"
    [ -n "${!__var}" ] && break
    warn "This value is required."
  done
}

# ask_secret VAR "Prompt" - hidden input, keeps asking until non-empty.
ask_secret() {
  local __var="$1" __msg="$2" __in
  while :; do
    printf '%s%s%s: ' "$C_BOLD" "$__msg" "$C_RESET" > /dev/tty
    read -rs __in < /dev/tty || true
    printf '\n' > /dev/tty
    if [ -n "$__in" ]; then
      printf -v "$__var" '%s' "$__in"
      break
    fi
    warn "This value is required."
  done
}

# confirm "Question" - returns 0 for yes (default), 1 for no.
confirm() {
  local __ans
  printf '%s%s%s [Y/n]: ' "$C_BOLD" "$1" "$C_RESET" > /dev/tty
  read -r __ans < /dev/tty || true
  case "$__ans" in
    [nN] | [nN][oO]) return 1 ;;
    *) return 0 ;;
  esac
}

# Generate a cryptographically random hex secret (32 bytes → 64 hex chars).
generate_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  elif [ -r /dev/urandom ]; then
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
  else
    python3 -c 'import secrets; print(secrets.token_hex(32))'
  fi
}

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    die "Please run this script as root."
  fi
}

install_base_packages() {
    if ! command -v apt-get >/dev/null; then
      die "This installer supports Debian/Ubuntu only."
    fi

    info "Installing base packages..."

    apt-get update
    apt-get install -y curl ca-certificates openssl git

    success "Base packages installed."
}

build_olcrtc(){
  info "Building OLCRTC container"
  cd backend/olcrtc

  docker build . --tag olcrtc

  cd ../..
}

build_xraycore(){
  info "Building XrayCore container"
  cd backend/xraycore

  docker build . --tag xraycore

  docker run -d --name olcwave-xraycore xraycore
  docker stop olcwave-xraycore

  cd ../..
}

enable_swapfile() {
    local SWAPFILE="/swapfile"
    local TARGET_GB=4
    local TARGET_KB=$((TARGET_GB * 1024 * 1024))

    local TOTAL_RAM_KB
    TOTAL_RAM_KB=$(awk '/MemTotal/ {print $2}' /proc/meminfo)

    if swapon --show --noheadings | grep -q .; then
        info "Swap already exists, skipping"
        swapon --show
        return 0
    fi

    if [ "$TOTAL_RAM_KB" -ge "$TARGET_KB" ]; then
        info "RAM >= ${TARGET_GB}GB, no swap required"
        return 0
    fi

    local SWAP_KB=$((TARGET_KB - TOTAL_RAM_KB))
    local SWAP_MB=$((SWAP_KB / 1000))

    if [ "$SWAP_MB" -le 0 ]; then
        info "No swap needed"
        return 0
    fi

    info "RAM is less than ${TARGET_GB}GB"
    info "Creating ${SWAP_MB}MB swapfile..."

    if [ -e "$SWAPFILE" ]; then
        info "${SWAPFILE} already exists but is not active, skipping"
        return 0
    fi

    dd if=/dev/zero \
       of="$SWAPFILE" \
       bs=1M \
       count="$SWAP_MB" \
       status=progress

    chmod 600 "$SWAPFILE"

    mkswap "$SWAPFILE"
    swapon "$SWAPFILE"

    if ! grep -q "^$SWAPFILE " /etc/fstab; then
        echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab
    fi

    success "Swap enabled:"
    free -h
}

# ---------------------------------------------------------------------------
# 1. Dependency checks and installs
# ---------------------------------------------------------------------------
install_docker() {
  info "Installing Docker..."

  if command -v docker >/dev/null 2>&1; then
    success "Docker already installed."
    return
  fi

  info "Downloading Docker installer..."

  curl -fsSL https://get.docker.com | sh

  systemctl enable --now docker

  success "Docker installed."
}

install_nodejs() {
  info "Installing Node.js..."

  if command -v npm >/dev/null 2>&1; then
    success "npm already installed."
    return
  fi

  info "Installing Node.js 20..."

  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -

  apt-get install -y nodejs

  success "Node.js installed."
}

check_dependencies() {
  info "Checking prerequisites..."

  if ! command -v docker >/dev/null 2>&1; then
    install_docker
  fi

  if ! docker compose version >/dev/null 2>&1; then
    die "'docker compose' is not available after Docker installation."
  fi

  if ! command -v npm >/dev/null 2>&1; then
    install_nodejs
  fi

  success "docker, docker compose and npm are present."

  docker --version
  docker compose version
  node --version
  npm --version
}

# ---------------------------------------------------------------------------
# 2. Collect configuration from the user
# ---------------------------------------------------------------------------
collect_input() {
  info "Configuration - answer the prompts below."
  printf '\n' > /dev/tty

  if confirm "Enable Remnawave integration?"; then
    RW_ENABLED=True

    ask_required RW_DOMAIN "Remnawave domain (e.g. remnawave.example.com)"
    RW_API_URL="https://${RW_DOMAIN}"

    ask_required RW_API_TOKEN "Remnawave API token"
    ask RW_CADDY_TOKEN "Caddy Auth token (Leave blank if you dont use it)" ""

    ask RW_SQUAD_NAME "Restrict to a specific Remnawave squad (name or UUID, leave empty to skip)" ""
  else
    RW_ENABLED=False
    RW_API_URL=""
    RW_API_TOKEN=""
    RW_CADDY_TOKEN=""
    RW_SQUAD_NAME=""
    info "Remnawave integration disabled - users will be created locally via the panel."
  fi

  ask ADMIN_USERNAME "Admin username" "admin"

  JWT_SECRET_KEY="$(generate_secret)"
  ADMIN_PASSWORD="$(generate_secret)"

  ask_required PANEL_DOMAIN "OLCWave Panel domain (e.g. olcwave.example.com)"
  PANEL_URL="https://${PANEL_DOMAIN}"
  VITE_API_URL="https://${PANEL_DOMAIN}/api"

  ROOT_DOMAIN="${PANEL_DOMAIN#*.}"

  ask SUB_DOMAIN "Subscription domain (e.g. sub.example.com)" "olcsub.${ROOT_DOMAIN}"
  SUB_URL_TEMPLATE="https://${SUB_DOMAIN}/{uuid}"

  POSTGRES_USER="olcwave"
  POSTGRES_DB="main"
  POSTGRES_PASSWORD="$(generate_secret)"
}

# ---------------------------------------------------------------------------
# 3. Generate env files
# ---------------------------------------------------------------------------

# Warn + confirm before clobbering an existing file. Returns 1 to skip.
may_overwrite() {
  local target="$1"
  [ -f "$target" ] || return 0
  confirm "$target already exists. Overwrite it?" || { warn "Kept existing $target."; return 1; }
  return 0
}

write_backend_env() {
  may_overwrite "backend/.env" || return 0
  # printf '%s' keeps values verbatim (safe for passwords with special chars).
  {
    printf 'RW_ENABLED=%s\n'                 "$RW_ENABLED"
    if [ "$RW_ENABLED" = "True" ]; then
      printf 'RW_API_URL=%s\n'               "$RW_API_URL"
      printf 'RW_API_TOKEN=%s\n'             "$RW_API_TOKEN"
      printf 'RW_CADDY_TOKEN=%s\n'           "$RW_CADDY_TOKEN"
      printf 'RW_SQUAD_NAME=%s\n'            "$RW_SQUAD_NAME"
    fi
    printf '\nDB_HOST=postgres\n'
    printf 'DB_PORT=5432\n'
    printf 'POSTGRES_USER=%s\n'              "$POSTGRES_USER"
    printf 'POSTGRES_PASSWORD=%s\n'          "$POSTGRES_PASSWORD"
    printf 'POSTGRES_DB=%s\n\n'              "$POSTGRES_DB"
    printf 'ADMIN_USERNAME=%s\n'             "$ADMIN_USERNAME"
    printf 'ADMIN_PASSWORD=%s\n\n'           "$ADMIN_PASSWORD"
    printf 'JWT_SECRET_KEY=%s\n'             "$JWT_SECRET_KEY"
    printf 'JWT_EXPIRE_MINUTES=1440\n'
  } > backend/.env
  success "Wrote backend/.env"
}

write_frontend_env() {
  may_overwrite "frontend/.env" || return 0
  {
    printf 'VITE_API_URL=%s\n'          "$VITE_API_URL"
    printf 'VITE_SUB_URL_TEMPLATE=%s\n' "$SUB_URL_TEMPLATE"
  } > frontend/.env
  success "Wrote frontend/.env"
}
  
write_compose_env() {
  # Shared secret between the api and the token vault sidecar (see vault/).
  # docker compose reads this file for the ${VAULT_SECRET} interpolation.
  may_overwrite ".env" || return 0
  printf 'VAULT_SECRET=%s\n' "$(generate_secret)" > .env
  chmod 600 .env
  success "Wrote .env (VAULT_SECRET)"
}

write_caddyfile() {
  info "Generating caddy/Caddyfile..."

  local template="caddy/Caddyfile.template"
  local target="caddy/Caddyfile"

  [ -f "$template" ] || die "$template not found."

  may_overwrite "$target" || return 0

  sed \
    -e "s|{{PANEL_DOMAIN}}|${PANEL_DOMAIN}|g" \
    -e "s|{{SUB_DOMAIN}}|${SUB_DOMAIN}|g" \
    "$template" > "$target"

  success "Generated caddy/Caddyfile"
}

# ---------------------------------------------------------------------------
# 4. Build the frontend  (Caddy serves frontend/dist)
# ---------------------------------------------------------------------------
build_frontend() {
  info "Building the frontend..."
  (
    cd frontend
    if [ -d node_modules ]; then
      info "node_modules present - skipping dependency install."
    else
      info "Installing dependencies (npm ci)..."
      if [ -f package-lock.json ]; then
        npm ci --no-audit
      else
        npm install
      fi
    fi
    npm run build
  )
  success "Frontend built into frontend/dist."
}

# ---------------------------------------------------------------------------
# 5. Build the subscription Page  (Caddy serves subscriptionPage/dist)
# ---------------------------------------------------------------------------
build_subscription_page() {
  info "Building the subscription page..."
  (
    cd subscriptionPage
    if [ -d node_modules ]; then
      info "node_modules present - skipping dependency install."
    else
      info "Installing dependencies (npm ci)..."
      if [ -f package-lock.json ]; then
        npm ci
      else
        npm install
      fi
    fi
    npm run build
  )
  success "subscriptionPage built into subscriptionPage/dist."
}

# ---------------------------------------------------------------------------
# 6. Start the Docker Compose stack
# ---------------------------------------------------------------------------
start_stack() {
  info "Building images and starting the stack (docker compose up -d --build)..."
  docker compose up -d --build
}

# ---------------------------------------------------------------------------
# 7. Verify the API container came up
# ---------------------------------------------------------------------------
verify_stack() {
  info "Waiting for the API container to start..."
  local running="" i
  # The API waits for Postgres to become healthy, so give it a little time.
  for i in $(seq 1 20); do
    running="$(docker inspect -f '{{.State.Running}}' olcwave-api 2>/dev/null || echo false)"
    [ "$running" = "true" ] && break
    sleep 3
  done

  if [ "$running" != "true" ]; then
    error "The API container (olcwave-api) is not running."
    error "Inspect the logs with:  docker compose logs api"
    docker compose ps || true
    exit 1
  fi

  success "API container is running."
  docker compose ps

  until curl -sf https://${PANEL_DOMAIN}/api/health >/dev/null; do
    info "waiting for api..."
        sleep 2
    done

  success "API is ready"
}

# ---------------------------------------------------------------------------
# 8. Final summary
# ---------------------------------------------------------------------------
print_summary() {
  local line="========================================"
  printf '\n%s%s%s\n\n' "$C_GREEN" "$line" "$C_RESET"
  printf '  %sOLCWave%s installed successfully%s\n\n' "$C_BOLD" "$C_GREEN" "$C_RESET"
  printf '  Panel\n    %s\n\n'                 "$PANEL_URL"
  printf '  Admin username\n    %s\n\n'        "$ADMIN_USERNAME"
  printf '  Admin password\n    %s\n\n'        "$ADMIN_PASSWORD"
  printf '  Subscription template\n    %s\n\n' "$SUB_URL_TEMPLATE"
  printf '  Containers\n    docker compose ps\n\n'
  printf '  API logs\n    docker compose logs -f api\n\n'
  printf '%s%s%s\n\n' "$C_GREEN" "$line" "$C_RESET"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
  require_root
  install_base_packages
  enable_swapfile
  check_dependencies
  collect_input
  write_backend_env
  write_frontend_env
  write_compose_env
  write_caddyfile
  build_frontend
  build_subscription_page
  build_olcrtc
  build_xraycore
  start_stack
  verify_stack
  print_summary
}

main "$@"
