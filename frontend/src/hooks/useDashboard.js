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
      const [kpis, pipeline, status] = await Promise.allSettled([
        api.kpis(),
        api.pipeline(),
        api.status(),
      ]);

      const k = kpis.status === 'fulfilled' ? kpis.value : null;
      const p = pipeline.status === 'fulfilled' ? pipeline.value : null;
      const s = status.status === 'fulfilled' ? status.value : null;

      setData({
        revenueGrowth: k?.receita_delta   ?? mockData.revenueGrowth,
        conversion:    k?.conversao        ?? mockData.conversion,
        hotLeads:      k?.leads_quentes    ?? mockData.hotLeads,
        margin:        k?.margem           ?? mockData.margin,
        revenue:       k?.receita          ?? mockData.revenue,
        profit:        k?.lucro            ?? mockData.profit,
        leads:         k?.leads            ?? mockData.leads,
        backendAlerts: k?.alertas          ?? [],
        pipeline:      p                   ?? mockData.pipeline,
        systemStatus:  s                   ?? mockData.systemStatus,
      });

      setError(null);
      setLastUpdate(new Date());
    } catch {
      // mantém estado atual
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
