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

const STAGE_ORDER = ['opportunity', 'product', 'content', 'video', 'sales', 'performance'];
const STAGE_LABEL = {
  opportunity: 'Oportunidade',
  product:     'Produto',
  content:     'Conteúdo',
  video:       'Vídeo',
  sales:       'Vendas',
  performance: 'Performance',
  idle:        'Aguardando',
};

function PipelineBar({ pipeline }) {
  const currentIdx = STAGE_ORDER.indexOf(pipeline?.fase);
  return (
    <div className="flex items-center gap-1">
      {STAGE_ORDER.map((stage, i) => {
        const done    = i < currentIdx;
        const active  = i === currentIdx && pipeline?.status !== 'idle';
        const waiting = i > currentIdx;
        return (
          <div key={stage} className="flex items-center gap-1">
            <div className={`
              text-[9px] font-bold px-2 py-1 rounded
              ${done    ? 'bg-green-500/20 text-green-400' : ''}
              ${active  ? 'bg-violet-500/30 text-violet-300 ring-1 ring-violet-500' : ''}
              ${waiting ? 'bg-white/5 text-gray-600' : ''}
            `}>
              {done ? '✓ ' : active ? '→ ' : '○ '}
              {STAGE_LABEL[stage]}
            </div>
            {i < STAGE_ORDER.length - 1 && (
              <div className={`w-3 h-px ${done ? 'bg-green-500/40' : 'bg-white/10'}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function Dashboard() {
  const { data, lastUpdate, reload } = useDashboard();

  const insights = generateInsights(data);
  const score    = calculateHealthScore(data);

  // Alertas: combina backend + decision engine
  const engineAlerts = insights
    .filter(i => i.type === 'ALERTA')
    .map(i => ({
      level: i.priority === 'critical' ? 'critical' : 'warning',
      title: i.message,
      reason: i.reason,
      action: i.action,
      link:   i.link,
    }));

  const backendAlerts = (data.backendAlerts || []).map(a => ({
    level: a.tipo === 'warn' ? 'warning' : 'info',
    title: a.titulo,
    reason: a.detalhe,
    action: a.acao,
  }));

  // Deduplicar: backend tem prioridade, só adiciona engine se não for duplicata de título
  const backendTitles = new Set(backendAlerts.map(a => a.title));
  const mergedAlerts = [
    ...backendAlerts,
    ...engineAlerts.filter(a => !backendTitles.has(a.title)),
  ];

  const pipeline     = data.pipeline   || {};
  const sysStatus    = data.systemStatus || {};
  const pipelineLabel = pipeline.fase_label || STAGE_LABEL[pipeline.fase] || '—';
  const pipelineInsight = pipeline.ultima_acao
    ? `${pipeline.ultima_acao} → ${pipeline.proximo_passo || 'Concluído'}`
    : null;

  return (
    <div className="flex h-screen bg-[#0a0e27] text-white overflow-hidden">
      <Sidebar />

      <main className="flex-1 p-6 overflow-y-auto">
        <Header lastUpdate={lastUpdate} onReload={reload} />

        {/* STATUS DO SISTEMA */}
        {sysStatus.total_problemas > 0 && (
          <div className="mb-4 flex flex-col gap-1.5">
            {sysStatus.problemas.map((p, i) => (
              <Alert key={i} level="warning" title={p} />
            ))}
          </div>
        )}

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
            value={pipelineLabel}
            colorClass="text-amber-400"
            insight={pipelineInsight}
          />
        </div>

        {/* PIPELINE VISUAL */}
        <div className="mb-5 bg-[#111633] border border-[#1f2a44] rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[10px] font-black uppercase tracking-widest text-amber-400">
              Pipeline — {pipeline.produto || '—'}
            </span>
            {pipeline.progresso > 0 && (
              <span className="text-[10px] text-gray-500">
                {pipeline.progresso}% concluído
                {pipeline.tempo_fase ? ` · ${pipeline.tempo_fase} nesta fase` : ''}
              </span>
            )}
          </div>
          <PipelineBar pipeline={pipeline} />
          {pipeline.progresso > 0 && (
            <div className="mt-3 h-1 bg-white/5 rounded-full overflow-hidden">
              <div
                className="h-full bg-violet-500 rounded-full transition-all"
                style={{ width: `${pipeline.progresso}%` }}
              />
            </div>
          )}
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
        {mergedAlerts.length > 0 && (
          <div className="flex flex-col gap-2">
            <span className="text-[10px] font-black uppercase tracking-widest text-red-400 mb-1">
              Alertas
            </span>
            {mergedAlerts.map((a, i) => (
              <Alert key={i} {...a} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
