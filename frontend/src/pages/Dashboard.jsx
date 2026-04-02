import { Sidebar }     from '../layout/Sidebar';
import { Header }      from '../layout/Header';
import { Card }        from '../components/ui/Card';
import { KPICard }     from '../components/ui/KPICard';
import { InsightCard } from '../components/ui/InsightCard';
import { Alert }       from '../components/ui/Alert';
import { HealthScore } from '../components/ui/HealthScore';
import { AreaChart }   from '../components/charts/AreaChart';
import { DonutChart }  from '../components/charts/DonutChart';

import { generateInsights }    from '../engine/decisionEngine';
import { calculateHealthScore } from '../engine/scoring';

import { useDashboard } from '../hooks/useDashboard';
import { areaData, donutData } from '../services/mockData';

const brl = (v) => 'R$\u00a0' + Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 0 });

export default function Dashboard() {
  const { data, lastUpdate, reload } = useDashboard();

  const insights = generateInsights(data);
  const score    = calculateHealthScore(data);

  const alerts = insights
    .filter(i => i.type === 'ALERTA')
    .map(i => ({
      level: i.priority === 'critical' ? 'critical' : 'warning',
      title: i.message,
      reason: i.reason,
      action: i.action,
      link:   i.link
    }));

  return (
    <div className="flex h-screen bg-[#0a0e27] text-white overflow-hidden">
      <Sidebar />

      <main className="flex-1 p-6 overflow-y-auto">
        <Header lastUpdate={lastUpdate} onReload={reload} />

        {/* HEALTH SCORE */}
        <div className="mb-5">
          <HealthScore score={score} />
        </div>

        {/* KPIs */}
        <div className="grid grid-cols-5 gap-3 mb-5">
          <KPICard
            title="Receita"
            value={brl(data.revenue)}
            delta={data.revenueGrowth}
            deltaLabel="vs projeção"
            colorClass="text-violet-400"
            insight={data.revenueGrowth > 5 ? 'Tráfego pago — escalar ads' : data.revenueGrowth < -5 ? 'Revisar aquisição' : null}
          />
          <KPICard
            title="Lucro"
            value={brl(data.profit)}
            colorClass="text-green-400"
            insight={data.margin > 50 ? `Margem ${data.margin}% — reinvestir 30%` : null}
          />
          <KPICard
            title="Conversão"
            value={`${data.conversion}%`}
            delta={data.conversion - 15}
            deltaLabel="vs meta"
            colorClass="text-sky-400"
            insight={data.conversion < 14 ? 'Requalificar funil' : data.conversion >= 17 ? 'Escalar geração' : null}
          />
          <KPICard
            title="Leads ativos"
            value={data.leads}
            colorClass="text-pink-400"
            insight={data.hotLeads > 0 ? `${data.hotLeads} quentes — contatar 24h` : null}
          />
          <KPICard
            title="Pipeline"
            value={data.pipeline || '—'}
            colorClass="text-amber-400"
          />
        </div>

        {/* GRÁFICOS */}
        <div className="grid grid-cols-12 gap-4 mb-5">
          <div className="col-span-8">
            <Card>
              <AreaChart data={areaData} />
            </Card>
          </div>
          <div className="col-span-4">
            <Card>
              <DonutChart data={donutData} />
            </Card>
          </div>
        </div>

        {/* INTELLIGENCE PANEL */}
        <div className="mb-5">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-[10px] font-black uppercase tracking-widest text-violet-400">
              Inteligência
            </span>
            <span className="text-[10px] text-gray-700">
              — {insights.length} insight{insights.length !== 1 ? 's' : ''} gerado{insights.length !== 1 ? 's' : ''}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-3">
            {insights.map((insight, i) => (
              <InsightCard key={i} insight={insight} />
            ))}
          </div>
        </div>

        {/* ALERTAS */}
        {alerts.length > 0 && (
          <div className="flex flex-col gap-2">
            <span className="text-[10px] font-black uppercase tracking-widest text-red-400 mb-1">
              Alertas
            </span>
            {alerts.map((a, i) => (
              <Alert key={i} {...a} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
