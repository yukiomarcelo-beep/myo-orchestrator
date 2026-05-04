export function calculateHealthScore(data) {
  let score = 0;

  // Margem (25 pts) — indicador mais estável
  const margin = data.margin ?? 0;
  score += margin >= 50 ? 25 : margin >= 35 ? 18 : margin >= 20 ? 10 : 0;

  // Conversão (25 pts)
  const conv = data.conversion ?? 0;
  score += Math.min(25, conv * 1.6);

  // Receita delta (20 pts) — 0% é neutro, não penaliza
  const delta = data.revenueGrowth ?? 0;
  score += delta >= 15 ? 20 : delta >= 5 ? 15 : delta >= 0 ? 10 : Math.max(0, 10 + delta);

  // Leads ativos (15 pts)
  score += Math.min(15, (data.leads ?? 0) * 1.5);

  // Hot leads (15 pts)
  score += Math.min(15, (data.hotLeads ?? 0) * 5);

  return Math.max(0, Math.min(100, Math.round(score)));
}
