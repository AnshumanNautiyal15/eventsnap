#!/usr/bin/env bash
# Deploy WeddingSnap from its git clone with gunicorn + nginx + HTTPS (Ubuntu 22.04/24.04).
#
# First time (inside the cloned repo, e.g. /srv/weddingsnap):
#   sudo bash deploy/deploy.sh photos.example.com you@example.com
#     -> creates .env with fresh secret keys and stops; add your R2 keys, then run the same command again.
#
# Every update afterwards (pulls the latest code from git, rebuilds, restarts):
#   sudo bash deploy/deploy.sh update
set -euo pipefail

APP="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER=weddingsnap
SERVICE=weddingsnap

[ "$(id -u)" = 0 ] || { echo "Run with sudo."; exit 1; }
step() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
as_app() { sudo -u "$APP_USER" -H "$@"; }

if [ "${1:-}" = "update" ]; then
  MODE=update
  [ -f "$APP/.env" ] || { echo "No .env yet: run the first-time command first (see top of this file)."; exit 1; }
  DOMAIN="$(grep -E '^DJANGO_ALLOWED_HOSTS=' "$APP/.env" | cut -d= -f2 | cut -d, -f1)"
else
  MODE=install
  DOMAIN="${1:?usage: sudo bash deploy/deploy.sh <domain> <email>   (or: sudo bash deploy/deploy.sh update)}"
  EMAIL="${2:?usage: sudo bash deploy/deploy.sh <domain> <email>}"
fi

case "$APP" in
  /root/*) echo "The repo is inside /root, which the app user can't read. Move it, then run this again from there:"
           echo "  mv $APP /srv/weddingsnap && cd /srv/weddingsnap"; exit 1 ;;
esac

# ---------------------------------------------------------------- first time only: system setup
if [ "$MODE" = install ]; then
  step "System packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q
  apt-get install -y -q python3 python3-venv python3-dev build-essential git nginx certbot python3-certbot-nginx ufw curl ca-certificates

  if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
    step "Node.js 22 (to build the app screens)"
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y -q nodejs
  fi

  step "Swap file (safety net for memory spikes)"
  if ! swapon --show | grep -q .; then
    fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi

  step "App user"
  id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --home-dir "/home/$APP_USER" --shell /usr/sbin/nologin "$APP_USER"

  if [ ! -f "$APP/.env" ]; then
    cp "$APP/deploy/.env.production.example" "$APP/.env"
    sed -i "s#photos.example.com#$DOMAIN#g" "$APP/.env"
    SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
    ENC=$(python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
    sed -i "s#^DJANGO_SECRET_KEY=.*#DJANGO_SECRET_KEY=$SECRET#; s#^DATA_ENCRYPTION_KEY=.*#DATA_ENCRYPTION_KEY=$ENC#" "$APP/.env"
    chown "$APP_USER:$APP_USER" "$APP/.env"; chmod 600 "$APP/.env"
    echo
    echo "Created $APP/.env with your domain and fresh secret keys."
    echo "Add your Cloudflare R2 details:   sudo nano $APP/.env"
    echo "Then run again:                   sudo bash deploy/deploy.sh $DOMAIN $EMAIL"
    exit 0
  fi
fi

grep -q '^R2_ACCESS_KEY_ID=.\+' "$APP/.env" || { echo "Fill in the R2_* values in $APP/.env first (sudo nano $APP/.env)."; exit 1; }
[ -f "$APP/ml_models/face_recognition_sface_2021dec.onnx" ] || { echo "ml_models/ is missing from the repo."; exit 1; }

# ---------------------------------------------------------------- code
git config --global --add safe.directory "$APP" 2>/dev/null || true
if [ "$MODE" = update ]; then
  if [ -f "$APP/db.sqlite3" ]; then
    step "Backing up the database before updating"
    as_app bash -c "cd '$APP' && .venv/bin/python manage.py backup_db"
  fi
  step "Pulling the latest code"
  git -C "$APP" pull --ff-only
fi
chown -R "$APP_USER:$APP_USER" "$APP"

step "Python packages"
[ -x "$APP/.venv/bin/python" ] || as_app python3 -m venv "$APP/.venv"
as_app "$APP/.venv/bin/pip" install -q --upgrade pip
as_app "$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"

step "Building the app screens"
as_app bash -c "cd '$APP/frontend' && npm ci --no-audit --no-fund --loglevel=error && npm run build --silent"

step "Database and static files"
as_app bash -c "cd '$APP' && .venv/bin/python manage.py migrate --noinput"
as_app bash -c "cd '$APP' && .venv/bin/python manage.py collectstatic --noinput -v0"
as_app bash -c "cd '$APP' && .venv/bin/python manage.py check --deploy --fail-level ERROR"

step "gunicorn service + nightly backup"
for unit in weddingsnap.service weddingsnap-backup.service; do
  sed "s#APP_DIR#$APP#g; s#APP_USER#$APP_USER#g" "$APP/deploy/$unit" > "/etc/systemd/system/$unit"
done
cp "$APP/deploy/weddingsnap-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now "$SERVICE" weddingsnap-backup.timer >/dev/null
systemctl restart "$SERVICE"

# ---------------------------------------------------------------- first time only: web server + HTTPS
if [ "$MODE" = install ]; then
  step "nginx"
  sed "s/DOMAIN/$DOMAIN/g" "$APP/deploy/nginx.conf" > /etc/nginx/sites-available/weddingsnap
  ln -sf /etc/nginx/sites-available/weddingsnap /etc/nginx/sites-enabled/weddingsnap
  rm -f /etc/nginx/sites-enabled/default
  nginx -t && systemctl reload nginx

  step "Firewall"
  ufw allow OpenSSH >/dev/null && ufw allow 'Nginx Full' >/dev/null && ufw --force enable >/dev/null

  step "HTTPS certificate"
  certbot certificates 2>/dev/null | grep -q "Domains: $DOMAIN" || certbot --nginx -d "$DOMAIN" -m "$EMAIL" --agree-tos --redirect -n
fi

step "Checking"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  curl -fsS -H "Host: $DOMAIN" -H "X-Forwarded-Proto: https" http://127.0.0.1:8000/healthz >/dev/null 2>&1 && break
  sleep 1
done
if curl -fsS -H "Host: $DOMAIN" -H "X-Forwarded-Proto: https" http://127.0.0.1:8000/healthz >/dev/null; then
  echo "gunicorn is running. Site: https://$DOMAIN"
else
  echo "gunicorn didn't answer. Last log lines:"; journalctl -u "$SERVICE" -n 40 --no-pager; exit 1
fi
if [ "$MODE" = install ]; then
  echo
  echo "Create your admin login:"
  echo "  sudo -u $APP_USER $APP/.venv/bin/python $APP/manage.py createsuperuser"
fi
