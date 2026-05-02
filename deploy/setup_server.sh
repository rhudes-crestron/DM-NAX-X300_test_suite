#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  DM-NAX Test Suite — Server Setup Script
#  Run as root on a fresh Ubuntu 22.04/24.04 LTS server
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

INSTALL_DIR="/opt/dmnax-test-suite"
SERVICE_USER="dmnax-test"
LOG_DIR="/var/log/dmnax-test"
REPO_URL="git@nj-github.crestron.crestron.com:CrestronEngineering/DM-NAX_test_suite.git"

echo "═══════════════════════════════════════════════════════════"
echo "  DM-NAX Test Suite — Server Setup"
echo "═══════════════════════════════════════════════════════════"

# 1. System packages
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git openssh-client nginx

# 2. Service user
echo "[2/7] Creating service user..."
if ! id "${SERVICE_USER}" &>/dev/null; then
    useradd -r -m -d /home/${SERVICE_USER} -s /bin/bash ${SERVICE_USER}
fi

# 3. Clone repository (skip if files already present — e.g. manual copy/rsync)
echo "[3/7] Cloning test suite..."
if [ -f "${INSTALL_DIR}/conftest.py" ]; then
    echo "  → Suite files already present at ${INSTALL_DIR}, skipping git clone."
    echo "  → To update later: cd ${INSTALL_DIR} && sudo -u ${SERVICE_USER} git pull origin master"
elif [ ! -d "${INSTALL_DIR}" ]; then
    # Clone as the invoking user if possible, fall back to root
    CLONE_USER="${SUDO_USER:-root}"
    sudo -u "${CLONE_USER}" git clone "${REPO_URL}" "${INSTALL_DIR}" || {
        echo "  ✗ Git clone failed. Copy suite files manually to ${INSTALL_DIR}/ and re-run."
        exit 1
    }
else
    CLONE_USER="${SUDO_USER:-root}"
    cd "${INSTALL_DIR}" && sudo -u "${CLONE_USER}" git pull origin master || \
        echo "  ⚠ Git pull failed — continuing with existing files."
fi
chown -R ${SERVICE_USER}:${SERVICE_USER} "${INSTALL_DIR}"

# 4. Python environment
echo "[4/7] Setting up Python virtual environment..."
sudo -u ${SERVICE_USER} python3 -m venv "${INSTALL_DIR}/venv"
sudo -u ${SERVICE_USER} "${INSTALL_DIR}/venv/bin/pip" install -q --upgrade pip
sudo -u ${SERVICE_USER} "${INSTALL_DIR}/venv/bin/pip" install -q \
    -r "${INSTALL_DIR}/requirements.txt" gunicorn

# 5. Logging directory
echo "[5/7] Setting up logging..."
mkdir -p "${LOG_DIR}"
chown ${SERVICE_USER}:${SERVICE_USER} "${LOG_DIR}"

# 6. Install systemd services
echo "[6/7] Installing systemd services..."
cp "${INSTALL_DIR}/deploy/dmnax-dashboard.service" /etc/systemd/system/
cp "${INSTALL_DIR}/deploy/dmnax-nightly.service"   /etc/systemd/system/
cp "${INSTALL_DIR}/deploy/dmnax-nightly.timer"     /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dmnax-dashboard.service
systemctl enable --now dmnax-nightly.timer

# 7. Nginx reverse proxy (port 80 → gunicorn 8080)
echo "[7/7] Configuring nginx..."
cat > /etc/nginx/sites-available/dmnax-dashboard <<'NGINX'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }

    location /static/ {
        alias /opt/dmnax-test-suite/static/;
        expires 7d;
    }
}
NGINX

ln -sf /etc/nginx/sites-available/dmnax-dashboard /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Setup Complete!"
echo ""
echo "  Dashboard:  http://<server-ip>"
echo "  Logs:       ${LOG_DIR}/"
echo "  Suite:      ${INSTALL_DIR}/"
echo ""
echo "  Services:"
echo "    systemctl status dmnax-dashboard"
echo "    systemctl status dmnax-nightly.timer"
echo ""
echo "  Manual run:"
echo "    sudo -u ${SERVICE_USER} ${INSTALL_DIR}/venv/bin/python3 \\"
echo "        ${INSTALL_DIR}/orchestrator.py --targets DM-NAX-4ZSA"
echo "═══════════════════════════════════════════════════════════"
