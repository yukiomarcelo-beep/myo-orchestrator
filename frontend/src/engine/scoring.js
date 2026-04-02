export function calculateHealthScore(data) {
  let score = 0;
  score += Math.min(40, data.revenueGrowth * 2);
  score += Math.min(30, data.conversion * 2);
  score += Math.min(30, data.hotLeads * 5);
  return Math.max(0, Math.min(100, Math.round(score)));
}
