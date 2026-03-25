#!/bin/bash
# MYO — Launcher (duplo clique para abrir)

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Tenta encontrar python3 em vários lugares
PYTHON=""
for p in /usr/local/bin/python3 /usr/bin/python3 /opt/homebrew/bin/python3 $(which python3 2>/dev/null); do
  if [ -x "$p" ]; then
    PYTHON="$p"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo ""
  echo "  ERRO: python3 não encontrado."
  echo "  Instale em: https://www.python.org"
  echo ""
  read -p "  Pressione Enter para fechar..."
  exit 1
fi

# Roda o menu
"$PYTHON" "$DIR/myo.py"

# Se sair com erro, mantém janela aberta
if [ $? -ne 0 ]; then
  echo ""
  read -p "  Pressione Enter para fechar..."
fi
