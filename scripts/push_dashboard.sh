#!/usr/bin/env bash
# Sincroniza o dashboard atual pro repo claude-dashboard → dispara deploy no Render.
#
# Uso:
#   ~/Documents/orchestrator/scripts/push_dashboard.sh [--force]
#
# Executa: regenera HTML → copia pro repo → commit + push se houve mudança.

set -euo pipefail

ORCH=/Users/marceloyukio/Documents/orchestrator
REPO=/Users/marceloyukio/claude-dashboard
GEN="$ORCH/scripts/generate_claude_dashboard.py"

# 1. Regenera claude_setup.html (estrutura)
/usr/local/bin/python3 "$GEN" >/dev/null

# 2. Copia HTMLs estáticos gerados localmente
cp "$ORCH/claude_setup.html"      "$REPO/index.html"
[ -f "$ORCH/dashboard.html" ]          && cp "$ORCH/dashboard.html"          "$REPO/dashboard.html"
[ -f "$ORCH/executive_dashboard.html" ] && cp "$ORCH/executive_dashboard.html" "$REPO/executive.html"
[ -f "$ORCH/myo_investor.html" ]       && cp "$ORCH/myo_investor.html"       "$REPO/investor.html"
[ -f "$ORCH/chart.umd.min.js" ]        && cp "$ORCH/chart.umd.min.js"        "$REPO/chart.umd.min.js"
[ -f "$ORCH/claude_setup_summary.json" ] && cp "$ORCH/claude_setup_summary.json" "$REPO/claude_setup_summary.json"

# Pitches ficam em ~/claude-dashboard/pitch-*.html — gerados por build_pitch.py, não copiar.

# 3. Commit se mudou
cd "$REPO"
if git diff --quiet && [ "${1:-}" != "--force" ]; then
  echo "↔ sem mudanças — Render já está atualizado"
  exit 0
fi

TIMESTAMP=$(date "+%Y-%m-%d %H:%M")
git add -A
git -c user.email=yukio.marcelo@gmail.com -c user.name="Marcelo Yukio" \
    commit -q -m "dashboard: atualização $TIMESTAMP"
git push -q

echo "✓ publicado — Render vai rebuilldar em ~1-2min"
echo "  url: https://claude-dashboard-tzat.onrender.com/"
