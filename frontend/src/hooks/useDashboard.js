import { useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';
import { mockData } from '../services/mockData';

export function useDashboard() {
  const [data, setData] = useState(mockData);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);

  const load = useCallback(async () => {
    try {
      const kpis = await api.kpis();
      setData({
        revenueGrowth: kpis.receita_delta ?? mockData.revenueGrowth,
        conversion:    kpis.conversao    ?? mockData.conversion,
        hotLeads:      kpis.leads_quentes ?? mockData.hotLeads,
        margin:        kpis.margem       ?? mockData.margin,
        revenue:       kpis.receita      ?? mockData.revenue,
        profit:        kpis.lucro        ?? mockData.profit,
        leads:         kpis.leads        ?? mockData.leads
      });
      setLastUpdate(new Date());
    } catch {
      // API indisponível — mantém mockData
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, [load]);

  return { data, loading, error, lastUpdate, reload: load };
}
