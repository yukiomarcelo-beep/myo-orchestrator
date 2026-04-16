#!/bin/bash
# NEXARA — Inicia n8n com variáveis de ambiente configuradas

# Env vars do Nexara — preencha os valores abaixo
export NEXARA_NOTION_DATABASE_ID="SEU_DATABASE_ID_AQUI"
export NEXARA_TELEGRAM_CHAT_ID="SEU_CHAT_ID_AQUI"
export NEXARA_ORQUESTRADOR_PORTA="8767"

# Inicia n8n
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"
nvm use 20

echo ""
echo "🚀 Iniciando n8n..."
echo "   Acesse: http://localhost:5678"
echo ""
echo "   Env vars carregadas:"
echo "   NEXARA_NOTION_DATABASE_ID = $NEXARA_NOTION_DATABASE_ID"
echo "   NEXARA_TELEGRAM_CHAT_ID   = $NEXARA_TELEGRAM_CHAT_ID"
echo "   NEXARA_ORQUESTRADOR_PORTA = $NEXARA_ORQUESTRADOR_PORTA"
echo ""

n8n start
