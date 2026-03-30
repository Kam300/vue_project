#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/familyone-vps"
SITE_ADDRESS=":8081"
PUBLIC_ORIGIN=""
API_HOST="127.0.0.1"
API_PORT="5001"
SERVICE_NAME="familyone-backend-vps"
NODE_MAJOR="22"
SWAP_MB="4096"
EMAIL=""
OPEN_UFW="true"

usage() {
  cat <<'EOF'
Usage:
  sudo bash infra/vps/setup-full-vps.sh [options]

Options:
  --app-dir <path>         App directory on VPS (default: /opt/familyone-vps)
  --site-address <value>   Caddy site address, e.g. :8081 or app.example.com
  --public-origin <url>    Public origin for backend/.env and CORS
  --api-host <value>       Backend bind host (default: 127.0.0.1)
  --api-port <value>       Backend bind port (default: 5001)
  --service-name <value>   systemd service name (default: familyone-backend-vps)
  --node-major <value>     Node.js major version to install (default: 22)
  --swap-mb <value>        Swap size in MB if no swap exists (default: 4096)
  --email <value>          Email for Caddy ACME account (optional)
  --skip-ufw               Do not touch UFW rules
  -h, --help               Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-dir)
      APP_DIR="${2:-}"
      shift 2
      ;;
    --site-address)
      SITE_ADDRESS="${2:-}"
      shift 2
      ;;
    --public-origin)
      PUBLIC_ORIGIN="${2:-}"
      shift 2
      ;;
    --api-host)
      API_HOST="${2:-}"
      shift 2
      ;;
    --api-port)
      API_PORT="${2:-}"
      shift 2
      ;;
    --service-name)
      SERVICE_NAME="${2:-}"
      shift 2
      ;;
    --node-major)
      NODE_MAJOR="${2:-}"
      shift 2
      ;;
    --swap-mb)
      SWAP_MB="${2:-}"
      shift 2
      ;;
    --email)
      EMAIL="${2:-}"
      shift 2
      ;;
    --skip-ufw)
      OPEN_UFW="false"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root: sudo bash infra/vps/setup-full-vps.sh ..." >&2
  exit 1
fi

if [[ ! -f "$APP_DIR/package.json" || ! -f "$APP_DIR/backend/telegram_service.py" ]]; then
  echo "App files not found in $APP_DIR" >&2
  exit 1
fi

log_step() {
  echo "==> $1"
}

wait_for_http() {
  local url="$1"
  local attempts="${2:-60}"
  local delay="${3:-2}"

  for ((i=1; i<=attempts; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done

  return 1
}

set_or_add_env_value() {
  local file_path="$1"
  local name="$2"
  local value="$3"

  mkdir -p "$(dirname "$file_path")"
  touch "$file_path"

  if grep -qE "^[[:space:]]*${name}=" "$file_path"; then
    sed -i "s|^[[:space:]]*${name}=.*|${name}=${value}|" "$file_path"
  else
    printf '%s=%s\n' "$name" "$value" >> "$file_path"
  fi
}

ensure_swap() {
  local swap_file="/swapfile-familyone-vps"

  if [[ "${SWAP_MB}" == "0" ]]; then
    return
  fi

  if swapon --noheadings --show | grep -q .; then
    return
  fi

  log_step "Creating swap (${SWAP_MB} MB)"
  if command -v fallocate >/dev/null 2>&1; then
    fallocate -l "${SWAP_MB}M" "$swap_file" || true
  fi

  if [[ ! -f "$swap_file" || ! -s "$swap_file" ]]; then
    dd if=/dev/zero of="$swap_file" bs=1M count="$SWAP_MB" status=progress
  fi

  chmod 600 "$swap_file"
  mkswap "$swap_file"
  swapon "$swap_file"

  if ! grep -qF "$swap_file none swap sw 0 0" /etc/fstab; then
    echo "$swap_file none swap sw 0 0" >> /etc/fstab
  fi
}

install_base_packages() {
  log_step "Installing base packages"
  apt update
  DEBIAN_FRONTEND=noninteractive apt install -y \
    build-essential \
    ca-certificates \
    cmake \
    curl \
    git \
    gnupg \
    gfortran \
    libjpeg-dev \
    liblapack-dev \
    libopenblas-dev \
    pkg-config \
    python3 \
    python3-dev \
    python3-venv \
    software-properties-common \
    ufw \
    unzip
}

install_node() {
  local current_major=""

  if command -v node >/dev/null 2>&1; then
    current_major="$(node -v | sed -E 's/^v([0-9]+).*/\1/')"
  fi

  if [[ -n "$current_major" && "$current_major" -ge "$NODE_MAJOR" ]]; then
    return
  fi

  log_step "Installing Node.js ${NODE_MAJOR}.x"
  curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
  DEBIAN_FRONTEND=noninteractive apt install -y nodejs
}

install_caddy() {
  if command -v caddy >/dev/null 2>&1; then
    return
  fi

  log_step "Installing Caddy"
  DEBIAN_FRONTEND=noninteractive apt install -y debian-keyring debian-archive-keyring apt-transport-https
  install -m 0755 -d /usr/share/keyrings
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  cat > /etc/apt/sources.list.d/caddy-stable.list <<'EOF'
deb [signed-by=/usr/share/keyrings/caddy-stable-archive-keyring.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main
EOF
  apt update
  DEBIAN_FRONTEND=noninteractive apt install -y caddy
}

infer_public_origin() {
  if [[ -n "$PUBLIC_ORIGIN" ]]; then
    return
  fi

  if [[ "$SITE_ADDRESS" =~ ^:([0-9]+)$ ]]; then
    local host_ip
    host_ip="$(hostname -I | awk '{print $1}')"
    PUBLIC_ORIGIN="http://${host_ip}:${BASH_REMATCH[1]}"
    return
  fi

  local first_host
  first_host="$(echo "$SITE_ADDRESS" | cut -d',' -f1 | xargs)"
  if [[ -n "$first_host" ]]; then
    PUBLIC_ORIGIN="https://${first_host}"
  fi
}

write_backend_env() {
  local env_file="$APP_DIR/backend/.env"
  local env_example="$APP_DIR/backend/.env.example"

  if [[ ! -f "$env_file" && -f "$env_example" ]]; then
    cp "$env_example" "$env_file"
  fi

  set_or_add_env_value "$env_file" "API_HOST" "$API_HOST"
  set_or_add_env_value "$env_file" "API_PORT" "$API_PORT"
  set_or_add_env_value "$env_file" "PUBLIC_ORIGIN" "$PUBLIC_ORIGIN"
  set_or_add_env_value "$env_file" "USE_CUDA" "false"
}

write_frontend_env() {
  local env_file="$APP_DIR/.env"
  touch "$env_file"
  set_or_add_env_value "$env_file" "VITE_API_BASE" "/api"
}

build_frontend() {
  log_step "Installing frontend packages"
  (
    cd "$APP_DIR"
    npm install --silent
    log_step "Building frontend"
    npm run build
  )
}

setup_python_env() {
  log_step "Preparing Python virtualenv"
  (
    cd "$APP_DIR/backend"

    if [[ ! -d ".venv" ]]; then
      python3 -m venv .venv
    fi

    source .venv/bin/activate
    pip install --upgrade pip setuptools wheel
    pip uninstall -y cmake >/dev/null 2>&1 || true
    rm -f .venv/bin/cmake .venv/bin/cpack .venv/bin/ctest || true
    hash -r

    export PATH="/usr/bin:/bin:$PATH"
    export CMAKE_BUILD_PARALLEL_LEVEL=1
    export MAKEFLAGS="-j1"
    export CFLAGS="${CFLAGS:-} -mno-sse4.1 -mno-sse4.2 -mno-avx -mno-avx2"
    export CXXFLAGS="${CXXFLAGS:-} -mno-sse4.1 -mno-sse4.2 -mno-avx -mno-avx2"
    export CMAKE_ARGS="-DDLIB_USE_CUDA=0 -DUSE_SSE2_INSTRUCTIONS=1 -DUSE_SSE4_INSTRUCTIONS=0 -DUSE_AVX_INSTRUCTIONS=0"

    /usr/bin/cmake --version
    find /root/.cache/pip -type f -name 'dlib-*.whl' -delete 2>/dev/null || true
    PIP_PREFER_BINARY=1 PIP_NO_BINARY=dlib pip install --no-cache-dir -r requirements.txt
  )
}

ensure_service_user() {
  if ! id -u familyone >/dev/null 2>&1; then
    useradd --system --create-home --home-dir /var/lib/familyone --shell /usr/sbin/nologin familyone
  fi

  chown -R familyone:familyone "$APP_DIR"
}

write_backend_service() {
  local service_file="/etc/systemd/system/${SERVICE_NAME}.service"

  log_step "Writing systemd service ${SERVICE_NAME}"
  cat > "$service_file" <<EOF
[Unit]
Description=FamilyOne backend (${SERVICE_NAME})
After=network.target

[Service]
Type=simple
User=familyone
Group=familyone
WorkingDirectory=${APP_DIR}/backend
Environment=PYTHONUNBUFFERED=1
ExecStart=${APP_DIR}/backend/.venv/bin/python ${APP_DIR}/backend/telegram_service.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
}

ensure_caddy_import() {
  mkdir -p /etc/caddy/conf.d

  if ! grep -qF 'import /etc/caddy/conf.d/*.caddy' /etc/caddy/Caddyfile; then
    printf '\nimport /etc/caddy/conf.d/*.caddy\n' >> /etc/caddy/Caddyfile
  fi
}

write_caddy_site() {
  local site_file="/etc/caddy/conf.d/${SERVICE_NAME}.caddy"
  local snippet_name
  local global_block=""

  snippet_name="$(echo "$SERVICE_NAME" | sed -E 's/[^A-Za-z0-9_]+/_/g')"

  if [[ -n "$EMAIL" ]]; then
    global_block="{\n  email ${EMAIL}\n}\n\n"
  fi

  log_step "Writing Caddy site ${SITE_ADDRESS}"
  printf "%b" "$global_block" > "$site_file"
  cat >> "$site_file" <<EOF
(familyone_vps_${snippet_name}) {
  encode gzip

  @legacy path /health /register_face /recognize_face /delete_face/* /list_faces /clear_all /generate_pdf /download_pdf/*

  handle_path /api/* {
    reverse_proxy ${API_HOST}:${API_PORT}
  }

  handle @legacy {
    reverse_proxy ${API_HOST}:${API_PORT}
  }

  handle {
    root * ${APP_DIR}/dist
    try_files {path} /index.html
    file_server
  }
}

${SITE_ADDRESS} {
  import familyone_vps_${snippet_name}
}
EOF

  caddy fmt --overwrite "$site_file" >/dev/null 2>&1 || true
}

open_firewall() {
  if [[ "$OPEN_UFW" != "true" ]]; then
    return
  fi

  ufw allow OpenSSH >/dev/null 2>&1 || true

  if [[ "$SITE_ADDRESS" =~ ^:([0-9]+)$ ]]; then
    ufw allow "${BASH_REMATCH[1]}/tcp" >/dev/null 2>&1 || true
  else
    ufw allow 80/tcp >/dev/null 2>&1 || true
    ufw allow 443/tcp >/dev/null 2>&1 || true
  fi

  ufw --force enable >/dev/null 2>&1 || true
}

restart_services() {
  log_step "Restarting services"
  systemctl daemon-reload
  systemctl enable --now "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  systemctl enable --now caddy
  systemctl restart caddy
}

health_checks() {
  log_step "Running health checks"

  if ! wait_for_http "http://${API_HOST}:${API_PORT}/health" 45 2; then
    echo "Backend failed to respond on http://${API_HOST}:${API_PORT}/health" >&2
    systemctl status "$SERVICE_NAME" --no-pager || true
    journalctl -u "$SERVICE_NAME" -n 80 --no-pager || true
    return 1
  fi

  if [[ "$SITE_ADDRESS" =~ ^:([0-9]+)$ ]]; then
    if ! wait_for_http "http://127.0.0.1:${BASH_REMATCH[1]}/api/health" 20 2; then
      echo "Caddy failed to proxy http://127.0.0.1:${BASH_REMATCH[1]}/api/health" >&2
      systemctl status caddy --no-pager || true
      journalctl -u caddy -n 80 --no-pager || true
      return 1
    fi
  fi
}

infer_public_origin
install_base_packages
ensure_swap
install_node
install_caddy
write_backend_env
write_frontend_env
build_frontend
setup_python_env
ensure_service_user
write_backend_service
ensure_caddy_import
write_caddy_site
open_firewall
restart_services
health_checks

echo
echo "Done."
echo "App dir:       ${APP_DIR}"
echo "Service:       ${SERVICE_NAME}"
echo "Site address:  ${SITE_ADDRESS}"
echo "Public origin: ${PUBLIC_ORIGIN}"
echo "Backend health: http://${API_HOST}:${API_PORT}/health"

if [[ "$SITE_ADDRESS" =~ ^:([0-9]+)$ ]]; then
  echo "Test URL:      ${PUBLIC_ORIGIN}"
else
  echo "Test URL:      https://$(echo "$SITE_ADDRESS" | cut -d',' -f1 | xargs)"
fi
