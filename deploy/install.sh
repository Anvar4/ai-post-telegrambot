#!/usr/bin/env bash
# VPS (Ubuntu 22.04/24.04, jumladan Oracle Cloud Always Free) ga oʻrnatish: sudo bash deploy/install.sh
# Oldin loyiha papkasiga .env nusxalangan boʻlsin.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "❌ .env yoʻq. Avval: cp .env.example .env && nano .env"
  exit 1
fi
# Windows'dan nusxalangan .env dagi CRLF qiymatlarga \r qoʻshib, tokenlarni buzadi
sed -i 's/\r$//' .env

# 1. Docker
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi

# 2. RAM 2 GB dan kam boʻlsa (Oracle E2.1.Micro — 1 GB) — 2 GB swap: Docker build xotirasiz qolmasin
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$MEM_MB" -lt 2000 ] && ! swapon --show | grep -q '/swapfile'; then
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "ℹ️ 2 GB swap qoʻshildi (RAM: ${MEM_MB} MB)"
fi

# 3. Panel manzili: https://<IP>.sslip.io (Caddy sertifikatni oʻzi oladi)
IP=$(curl -fsS https://api.ipify.org)
HOST="${IP//./-}.sslip.io"
grep -q '^WEBAPP_HOST=' .env || echo "WEBAPP_HOST=${HOST}" >> .env
if grep -q '^WEBAPP_URL=$' .env || ! grep -q '^WEBAPP_URL=' .env; then
  sed -i '/^WEBAPP_URL=$/d' .env
  echo "WEBAPP_URL=https://${HOST}" >> .env
fi

# 4. Portlar 80/443: ufw (oddiy VPS) va iptables (Oracle Ubuntu image'ida portlar iptables bilan yopiq)
ufw allow 80/tcp >/dev/null 2>&1 || true
ufw allow 443/tcp >/dev/null 2>&1 || true
if command -v iptables >/dev/null; then
  for port in 80 443; do
    iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
      || iptables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
  done
  if command -v netfilter-persistent >/dev/null; then
    netfilter-persistent save >/dev/null 2>&1 || true
  fi
fi

# 5. Konteyner 1000-foydalanuvchi bilan ishlaydi — data papkasiga yozish huquqi
mkdir -p data
chown -R 1000:1000 data

docker compose up -d --build
echo "✅ Bot ishga tushdi. Panel: https://${HOST}  (botga /start yozing — pastda «📱 Panel» tugmasi chiqadi)"
echo "   Loglar: docker compose logs -f --tail=100 bot"
