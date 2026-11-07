#!/usr/bin/env bash
# VPS (Ubuntu 22.04/24.04) ga oʻrnatish: sudo bash deploy/install.sh
# Oldin loyiha papkasiga .env nusxalangan boʻlsin.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi

IP=$(curl -fsS https://api.ipify.org)
HOST="${IP//./-}.sslip.io"
grep -q '^WEBAPP_HOST=' .env || echo "WEBAPP_HOST=${HOST}" >> .env
if grep -q '^WEBAPP_URL=$' .env; then
  sed -i "s|^WEBAPP_URL=$|WEBAPP_URL=https://${HOST}|" .env
fi

ufw allow 80/tcp >/dev/null 2>&1 || true
ufw allow 443/tcp >/dev/null 2>&1 || true

docker compose up -d --build
echo "✅ Bot ishga tushdi. Panel: https://${HOST}  (botga /start yozing — pastda «📱 Panel» tugmasi chiqadi)"
