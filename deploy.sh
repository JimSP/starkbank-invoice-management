#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Configuração
# -----------------------------------------------------------------------------
SSH_KEY="./ssh-key.key"
REMOTE_USER="ubuntu"
REMOTE_HOST="163.176.208.167"
REMOTE_DIR="/opt/starkbank-invoice-management"

# -----------------------------------------------------------------------------
# Validações
# -----------------------------------------------------------------------------
if [ ! -f "$SSH_KEY" ]; then
  echo "❌ Chave SSH não encontrada: $SSH_KEY"
  exit 1
fi

if [ ! -f ".env" ]; then
  echo "❌ Arquivo .env local não encontrado! O deploy precisa dele para sincronizar as configs."
  exit 1
fi

chmod 600 "$SSH_KEY"

echo "→ 1/4 Preparando o servidor remoto (rsync e permissões) ..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$REMOTE_USER@$REMOTE_HOST" << PREPARE_SERVER
  sudo apt-get update -qq
  sudo apt-get install -y -qq rsync
  sudo mkdir -p "$REMOTE_DIR"
  sudo chown -R "$REMOTE_USER":"$REMOTE_USER" "$REMOTE_DIR"
PREPARE_SERVER

# -----------------------------------------------------------------------------
# 1. Sync dos arquivos (AGORA INCLUINDO O .ENV)
# -----------------------------------------------------------------------------
echo "→ 2/4 Sincronizando arquivos via rsync ..."
rsync -avz --progress \
  --exclude '.venv/' \
  --exclude '.vscode/' \
  --exclude '__pycache__/' \
  --exclude '*.py[cod]' \
  --exclude '.pytest_cache/' \
  --exclude 'htmlcov/' \
  --exclude '.coverage' \
  --exclude '.git/' \
  --exclude 'ssh-key.*' \
  --exclude 'deploy.sh' \
  -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
  ./ "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR"

# -----------------------------------------------------------------------------
# 2. Setup remoto
# -----------------------------------------------------------------------------
echo "→ 3/4 Iniciando setup remoto e Systemd ..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$REMOTE_USER@$REMOTE_HOST" \
  REMOTE_DIR="$REMOTE_DIR" \
  bash << 'REMOTE'

set -e
cd "$REMOTE_DIR"

echo "  - Instalando Python e dependências ..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip

echo "  - Configurando ambiente virtual ..."
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

# Proteção do arquivo de ambiente
chmod 600 .env

echo "  - Atualizando serviço Systemd ..."
sudo tee /etc/systemd/system/starkbank.service > /dev/null << SERVICE
[Unit]
Description=Stark Bank Invoice Management
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=${REMOTE_DIR}
EnvironmentFile=${REMOTE_DIR}/.env
ExecStart=${REMOTE_DIR}/.venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable starkbank
sudo systemctl restart starkbank

echo "→ 4/4 Verificando status ..."
sleep 2
sudo systemctl status starkbank --no-pager

echo ""
echo "✅ DEPLOY CONCLUÍDO COM SUCESSO!"
echo "   Endpoint: https://webhook.robotservice.com.br/health"
echo "   Logs: sudo journalctl -u starkbank -f"

REMOTE