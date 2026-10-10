#!/usr/bin/env bash
# Run on the new Ubuntu VM after copying the source archive. Contains no secrets.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
test "$(id -u)" = 0 || { echo 'Run with sudo.'; exit 1; }
test -f /tmp/gyeopnun-source.tar.gz
apt-get update
apt-get install -y python3-venv python3-dev build-essential curl ca-certificates zstd caddy
id -u gyeopnun >/dev/null 2>&1 || useradd --system --create-home --home-dir /srv/gyeopnun --shell /usr/sbin/nologin gyeopnun
install -d -o gyeopnun -g gyeopnun /srv/gyeopnun/app /srv/gyeopnun/data
install -d -m 700 /etc/gyeopnun
tar -xzf /tmp/gyeopnun-source.tar.gz -C /srv/gyeopnun/app
python3 -m venv /srv/gyeopnun/venv
/srv/gyeopnun/venv/bin/pip install --disable-pip-version-check -c /srv/gyeopnun/app/requirements.lock /srv/gyeopnun/app
chown -R gyeopnun:gyeopnun /srv/gyeopnun
# Use --skip-models when the same model setup is already running via Azure Run Command.
if [ "${1:-}" != "--skip-models" ]; then
# Match the locally validated Ollama version; API listens only on loopback.
curl --fail --silent --show-error --location https://ollama.com/install.sh -o /tmp/gyeopnun-ollama-install.sh
OLLAMA_VERSION=0.40.2 sh /tmp/gyeopnun-ollama-install.sh
install -d /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/gyeopnun.conf <<'EOF'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
EOF
systemctl daemon-reload
systemctl restart ollama
sudo -u ollama -H ollama pull gemma4:e2b
sudo -u ollama -H ollama pull bge-m3
fi
install -m 644 /srv/gyeopnun/app/deploy/azure/gyeopnun.service /etc/systemd/system/gyeopnun.service
systemctl daemon-reload
# Start only after private app.env and an HTTPS Caddy site have been supplied.
echo 'Bootstrap complete. Configure /etc/gyeopnun/app.env and /etc/caddy/Caddyfile before starting gyeopnun.'
