#!/usr/bin/env bash
set -euo pipefail

FRP_VERSION="0.67.0"
DOMAIN=""
TOKEN=""
EMAIL=""
SKIP_UFW="false"

usage() {
  cat <<'EOF'
Usage:
  sudo bash infra/frp/setup-frps.sh --domain totalcode.online [options]

Options:
  --domain <name>       Public domain, e.g. totalcode.online (required)
  --token <value>       FRP auth token. If omitted, generated automatically
  --email <value>       Email for Caddy ACME account (recommended)
  --frp-version <ver>   FRP version without "v", default: 0.67.0
  --skip-ufw            Do not touch UFW firewall rules
  -h, --help            Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      DOMAIN="${2:-}"
      shift 2
      ;;
    --token)
      TOKEN="${2:-}"
      shift 2
      ;;
    --email)
      EMAIL="${2:-}"
      shift 2
      ;;
    --frp-version)
      FRP_VERSION="${2:-}"
      shift 2
      ;;
    --skip-ufw)
      SKIP_UFW="true"
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

if [[ -z "$DOMAIN" ]]; then
  echo "Error: --domain is required" >&2
  usage
  exit 1
fi

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root: sudo bash infra/frp/setup-frps.sh --domain $DOMAIN" >&2
  exit 1
fi

if [[ -z "$TOKEN" ]]; then
  TOKEN="$(openssl rand -hex 32)"
fi

WWW_DOMAIN="www.${DOMAIN}"
FRP_ARCHIVE="frp_${FRP_VERSION}_linux_amd64.tar.gz"
FRP_URL="https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/${FRP_ARCHIVE}"

echo "==> Installing packages"
apt update
DEBIAN_FRONTEND=noninteractive apt install -y curl tar openssl ufw ca-certificates gnupg debian-keyring debian-archive-keyring apt-transport-https

if ! DEBIAN_FRONTEND=noninteractive apt install -y caddy; then
  echo "==> Caddy package not found in current apt sources. Adding official Caddy repo..."
  install -m 0755 -d /usr/share/keyrings
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  cat > /etc/apt/sources.list.d/caddy-stable.list <<'EOF'
deb [signed-by=/usr/share/keyrings/caddy-stable-archive-keyring.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main
EOF
  apt update
  DEBIAN_FRONTEND=noninteractive apt install -y caddy
fi

echo "==> Installing frps ${FRP_VERSION}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
curl -fsSL "$FRP_URL" -o "${tmp_dir}/${FRP_ARCHIVE}"
tar -xzf "${tmp_dir}/${FRP_ARCHIVE}" -C "$tmp_dir"
install -m 0755 "${tmp_dir}/frp_${FRP_VERSION}_linux_amd64/frps" /usr/local/bin/frps

echo "==> Writing /etc/frp/frps.toml"
mkdir -p /etc/frp
cat > /etc/frp/frps.toml <<EOF
bindPort = 7000
vhostHTTPPort = 8080

[auth]
method = "token"
token = "${TOKEN}"
EOF

echo "==> Creating frps systemd service"
cat > /etc/systemd/system/frps.service <<'EOF'
[Unit]
Description=frp server
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frps -c /etc/frp/frps.toml
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo "==> Configuring Caddy"
if [[ -n "$EMAIL" ]]; then
  cat > /etc/caddy/Caddyfile <<EOF
{
  email ${EMAIL}
}

${DOMAIN}, ${WWW_DOMAIN} {
  encode gzip
  reverse_proxy 127.0.0.1:8080 {
    header_up Host {http.request.host}
    header_up X-Forwarded-Host {http.request.host}
  }
}
EOF
else
  cat > /etc/caddy/Caddyfile <<EOF
${DOMAIN}, ${WWW_DOMAIN} {
  encode gzip
  reverse_proxy 127.0.0.1:8080 {
    header_up Host {http.request.host}
    header_up X-Forwarded-Host {http.request.host}
  }
}
EOF
fi

if [[ "$SKIP_UFW" != "true" ]]; then
  echo "==> Configuring UFW"
  ufw allow OpenSSH
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw allow 7000/tcp
  ufw --force enable
fi

echo "==> Starting services"
systemctl daemon-reload
systemctl enable --now frps
systemctl enable --now caddy
systemctl restart caddy

echo
echo "Done."
echo "Domain: ${DOMAIN}"
echo "FRP token: ${TOKEN}"
echo
echo "Next steps on Windows:"
echo "  1) Set backend/.env: PUBLIC_ORIGIN=https://${DOMAIN} and USE_CLOUDFLARED=false"
echo "  2) Run scripts/setup-frpc.ps1 with this token"
echo
