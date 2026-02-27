#!/usr/bin/env bash
# =============================================================================
# setup_server.sh
#
# Configura nginx + Let's Encrypt (certbot) no servidor remoto.
# Deve ser executado APÓS a propagação DNS do subdomínio.
#
# Uso:
#   bash setup_server.sh
# =============================================================================
set -euo pipefail

# -----------------------------------------------------------------------------
# Carregar variáveis do arquivo .env
# -----------------------------------------------------------------------------
ENV_FILE=".env"

if [ -f "$ENV_FILE" ]; then
  echo "→ Carregando configurações de $ENV_FILE..."
  # Exporta as variáveis para que fiquem disponíveis
  export $(grep -v '^#' "$ENV_FILE" | xargs)
else
  echo "❌ Arquivo $ENV_FILE não encontrado!"
  exit 1
fi

# -----------------------------------------------------------------------------
# Validação das variáveis críticas
# -----------------------------------------------------------------------------
: "${SSH_KEY:?Variável SSH_KEY não definida no .env}"
: "${REMOTE_HOST:?Variável REMOTE_HOST não definida no .env}"
: "${EMAIL:?Variável EMAIL não definida no .env}"

if [ ! -f "$SSH_KEY" ]; then
  echo "❌ Chave SSH não encontrada: $SSH_KEY"
  exit 1
fi

chmod 600 "$SSH_KEY"

# Verifica se o DNS já propagou
echo "→ Verificando propagação DNS de $DOMAIN …"
RESOLVED=$(dig +short "$DOMAIN" 2>/dev/null || true)
if [ "$RESOLVED" != "$REMOTE_HOST" ]; then
  echo "⚠️  DNS ainda não propagou (resolveu para: '${RESOLVED:-nenhum}')"
  echo "   Aguarde alguns minutos e tente novamente."
  exit 1
fi
echo "✅ DNS ok — $DOMAIN → $RESOLVED"

# -----------------------------------------------------------------------------
# Setup remoto
# -----------------------------------------------------------------------------
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$REMOTE_USER@$REMOTE_HOST" \
  DOMAIN="$DOMAIN" \
  APP_PORT="$APP_PORT" \
  EMAIL="$EMAIL" \
  bash << 'REMOTE'

set -e

echo "→ Instalando nginx e certbot …"
sudo apt-get update -qq
sudo apt-get install -y -qq nginx certbot python3-certbot-nginx

# -----------------------------------------------------------------------------
# Configuração nginx (HTTP primeiro — certbot vai completar com HTTPS)
# -----------------------------------------------------------------------------
echo "→ Configurando nginx …"
sudo tee /etc/nginx/sites-available/starkbank > /dev/null << NGINX
server {
    listen 80;
    server_name ${DOMAIN};

    location / {
        proxy_pass         http://127.0.0.1:${APP_PORT};
        proxy_http_version 1.1;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
    }
}
NGINX

sudo ln -sf /etc/nginx/sites-available/starkbank /etc/nginx/sites-enabled/starkbank
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t
sudo systemctl reload nginx

# -----------------------------------------------------------------------------
# Firewall
# -----------------------------------------------------------------------------
echo "→ Abrindo portas no firewall …"
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable

# -----------------------------------------------------------------------------
# Let's Encrypt
# -----------------------------------------------------------------------------
echo "→ Emitindo certificado SSL …"
sudo certbot --nginx \
  --non-interactive \
  --agree-tos \
  --email "$EMAIL" \
  --domains "$DOMAIN" \
  --redirect

# -----------------------------------------------------------------------------
# Renovação automática
# -----------------------------------------------------------------------------
echo "→ Verificando renovação automática …"
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer
sudo certbot renew --dry-run

echo ""
echo "✅ Servidor configurado!"
echo "   Webhook URL: https://${DOMAIN}/webhook"
echo "   Health:      https://${DOMAIN}/health"

REMOTE