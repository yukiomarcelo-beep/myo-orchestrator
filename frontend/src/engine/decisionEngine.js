export function generateInsights(data) {
  const insights = [];

  if (data.revenueGrowth > 10) {
    insights.push({
      type: 'OPORTUNIDADE',
      priority: 'high',
      message: 'Receita crescendo forte',
      reason: 'Aumento de tráfego pago',
      action: 'Escalar investimento em ads',
      link: '/vendas?tab=campanhas'
    });
  }

  if (data.revenueGrowth < -10) {
    insights.push({
      type: 'ALERTA',
      priority: 'critical',
      message: 'Queda relevante de receita',
      reason: 'Baixa entrada de tráfego',
      action: 'Revisar aquisição imediatamente',
      link: '/vendas?tab=campanhas'
    });
  }

  if (data.conversion < 15) {
    insights.push({
      type: 'ALERTA',
      priority: 'high',
      message: 'Conversão abaixo da meta',
      reason: 'Leads pouco qualificados',
      action: 'Requalificar funil de vendas',
      link: '/vendas?tab=funil'
    });
  }

  if (data.conversion >= 17) {
    insights.push({
      type: 'OPORTUNIDADE',
      priority: 'high',
      message: `Conversão em ${data.conversion}% — acima da meta`,
      reason: 'Qualidade dos leads melhorou',
      action: 'Aumentar volume de geração de leads',
      link: '/vendas?tab=funil'
    });
  }

  if (data.hotLeads > 0) {
    insights.push({
      type: 'RECOMENDAÇÃO',
      priority: 'high',
      message: `${data.hotLeads} leads quentes aguardando`,
      reason: 'Alta intenção de compra nas últimas 24h',
      action: 'Entrar em contato em até 24h',
      link: '/crm'
    });
  }

  if (data.margin > 50) {
    insights.push({
      type: 'PADRÃO',
      priority: 'medium',
      message: `Margem em ${data.margin}% — saudável`,
      reason: 'CAC controlado, LTV crescendo',
      action: 'Reinvestir 30% do lucro em conteúdo',
      link: '/relatorios?tab=financeiro'
    });
  }

  if (insights.length === 0) {
    insights.push({
      type: 'RECOMENDAÇÃO',
      priority: 'medium',
      message: 'Sistema operando dentro do esperado',
      reason: 'Todos os KPIs dentro das faixas normais',
      action: 'Ver análise completa de performance',
      link: '/relatorios?tab=performance'
    });
  }

  return insights;
}
