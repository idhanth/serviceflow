#!/usr/bin/env bash
# One-time setup for an Oracle Cloud Always Free ARM instance (Ubuntu 24.04).
#
#   curl -fsSL <raw-url>/bootstrap.sh | sudo bash
#
# Installs Python, uv and Caddy, creates the service account and directories,
# and opens ports. It does not deploy the application and never touches secrets:
# /etc/serviceflow/api.env is written by hand afterwards.
set -euo pipefail

APP_USER=serviceflow
APP_ROOT=/opt/serviceflow
STATE_DIR=/var/lib/serviceflow

echo "==> packages"
apt-get update -qq
apt-get install -y -qq python3.12 python3.12-venv git curl ca-certificates debian-keyring \
  debian-archive-keyring apt-transport-https

echo "==> caddy"
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy
fi

echo "==> service account"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash "$APP_USER"
install -d -o "$APP_USER" -g "$APP_USER" "$APP_ROOT" "$APP_ROOT/releases" "$STATE_DIR"
# root writes the secrets; the app user only reads them. 750 on the directory
# and 640 on the file below is what lets deploy.sh source it without making it
# world-readable.
install -d -o root -g "$APP_USER" -m 750 /etc/serviceflow

echo "==> deploy script"
install -o "$APP_USER" -g "$APP_USER" -m 750 "$(dirname "$0")/deploy.sh" "$APP_ROOT/deploy.sh"

echo "==> uv (for the app user)"
sudo -u "$APP_USER" -H sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'

echo "==> permissions for deploying"
# The app user restarts only its own three units, and the administrator runs the
# deploy as the app user. Both are exact commands, not a general sudo grant.
cat > /etc/sudoers.d/serviceflow <<SUDO
$APP_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart serviceflow-api, \
/usr/bin/systemctl restart serviceflow-worker, \
/usr/bin/systemctl restart serviceflow-beat
%sudo ALL=($APP_USER) NOPASSWD: $APP_ROOT/deploy.sh
SUDO
chmod 440 /etc/sudoers.d/serviceflow
visudo -cf /etc/sudoers.d/serviceflow

echo "==> firewall"
# Oracle images ship with a REJECT-everything iptables policy in addition to the
# cloud security list, so both have to be opened or the box looks dead.
iptables -I INPUT -p tcp --dport 80 -j ACCEPT
iptables -I INPUT -p tcp --dport 443 -j ACCEPT
netfilter-persistent save 2>/dev/null || true

echo
echo "Next:"
echo "  1. Open 80 and 443 in the OCI security list for this VNIC."
echo "  2. Point your DNS A record at this machine's public IP."
echo "  3. Write /etc/serviceflow/api.env from deploy/oracle/api.env.example, then:"
echo "       chown root:$APP_USER /etc/serviceflow/api.env && chmod 640 /etc/serviceflow/api.env"
echo "  4. Put the Caddyfile at /etc/caddy/Caddyfile and set API_PROXY_TOKEN in"
echo "     /etc/systemd/system/caddy.service.d/env.conf, then: systemctl restart caddy"
echo "  5. SERVICEFLOW_REPO=<git-url> sudo -u $APP_USER -H $APP_ROOT/deploy.sh main"
