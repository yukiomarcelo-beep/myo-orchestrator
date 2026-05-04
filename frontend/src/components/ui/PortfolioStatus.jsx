import { useState, useEffect } from 'react';

const STATUS_DOT = {
  healthy:     'bg-green-400',
  running:     'bg-amber-400 animate-pulse',
  idle:        'bg-gray-600',
  warning:     'bg-yellow-400',
  planning:    'bg-sky-400',
  in_progress: 'bg-violet-400 animate-pulse',
  down:        'bg-red-400',
  error:       'bg-red-400',
  not_found:   'bg-gray-700',
};

const STATUS_LABEL = {
  healthy:     'Saudável',
  running:     'Rodando',
  idle:        'Idle',
  warning:     'Atenção',
  planning:    'Planejamento',
  in_progress: 'Em progresso',
  down:        'Down',
  error:       'Erro',
  not_found:   'Não encontrado',
};

const STATUS_TEXT = {
  healthy:     'text-green-400',
  running:     'text-amber-400',
  idle:        'text-gray-500',
  warning:     'text-yellow-400',
  planning:    'text-sky-400',
  in_progress: 'text-violet-400',
  down:        'text-red-400',
  error:       'text-red-400',
  not_found:   'text-gray-600',
};

function Dot({ status }) {
  return <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT[status] ?? 'bg-gray-600'}`} />;
}

function ProjectCard({ name, emoji, status, children }) {
  const textCls = STATUS_TEXT[status] ?? 'text-gray-500';
  return (
    <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-3">
      <div className="flex items-center gap-2 mb-2.5">
        <Dot status={status} />
        <span className="text-[11px] font-bold text-white">{emoji} {name}</span>
        <span className={`ml-auto text-[10px] font-bold ${textCls}`}>
          {STATUS_LABEL[status] ?? status}
        </span>
      </div>
      <div className="flex flex-col gap-1">{children}</div>
    </div>
  );
}

function Metric({ label, value, highlight }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[10px] text-gray-600">{label}</span>
      <span className={`text-[11px] font-semibold ${highlight ? 'text-white' : 'text-gray-400'}`}>{value}</span>
    </div>
  );
}

export function PortfolioStatus() {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [ts,      setTs]      = useState(null);

  useEffect(() => {
    const load = () =>
      fetch('/api/portfolio/status')
        .then(r => r.json())
        .then(d => { setData(d.projects); setTs(d.timestamp); setLoading(false); })
        .catch(() => setLoading(false));

    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  if (loading) return (
    <div className="bg-[#111633] border border-[#1f2a44] rounded-xl p-4 mb-5">
      <span className="text-[10px] font-black uppercase tracking-widest text-violet-400">Portfolio</span>
      <p className="text-[11px] text-gray-700 mt-2">Carregando...</p>
    </div>
  );

  if (!data) return null;

  const myo     = data.myo     ?? {};
  const kitchen = data.kitchen ?? {};
  const forja   = data.forja   ?? {};

  const myoStatus = myo.status ?? 'idle';

  return (
    <div className="bg-[#111633] border border-[#1f2a44] rounded-xl p-4 mb-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] font-black uppercase tracking-widest text-violet-400">
          Portfolio de Projetos
        </span>
        {ts && (
          <span className="text-[9px] text-gray-700">
            {new Date(ts).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
      </div>

      <div className="grid grid-cols-3 gap-3">

        {/* MYO OS */}
        <ProjectCard name="MYO OS" emoji="🤖" status={myoStatus}>
          <Metric label="Produtos ativos"    value={myo.produtos_ativos ?? 0} highlight={myo.produtos_ativos > 0} />
          <Metric label="Com erro"           value={myo.produtos_erro ?? 0}   highlight={myo.produtos_erro > 0} />
          <Metric label="Total no pipeline"  value={myo.total_produtos ?? 0} />
          <Metric label="Autonomia"          value={['Manual','Assistido','Autônomo'][myo.autonomous_level] ?? '—'} />
        </ProjectCard>

        {/* Kitchen / Nexxor */}
        <ProjectCard name="Kitchen" emoji="🍳" status={kitchen.status ?? 'down'}>
          {kitchen.db === 'up' ? (
            <>
              <Metric label="NFs processadas"   value={kitchen.nfs_total}  highlight />
              <Metric label="NFs (7 dias)"       value={kitchen.nfs_7d} />
              <Metric label="SKUs catalogados"   value={kitchen.skus} />
              <Metric label="Pratos c/ CMV"      value={kitchen.pratos} />
              {kitchen.ultima_nf && (
                <Metric
                  label="Última NF"
                  value={`#${kitchen.ultima_nf} · ${kitchen.ultima_nf_ago_h?.toFixed(0)}h atrás`}
                />
              )}
              {kitchen.alertas_ativos > 0 && (
                <Metric label="Alertas abertos"  value={kitchen.alertas_ativos} highlight />
              )}
            </>
          ) : (
            <p className="text-[10px] text-red-400">{kitchen.error ?? 'DB offline'}</p>
          )}
        </ProjectCard>

        {/* Forja */}
        <ProjectCard name="Forja" emoji="🔥" status={forja.status ?? 'not_found'}>
          <Metric label="Fase"        value="Fase 1" />
          <Metric label="Situação"    value="Aguardando cliente" />
          {forja.last_commit_ago_d != null && (
            <Metric label="Último commit" value={`${forja.last_commit_ago_d}d atrás`} />
          )}
          {forja.last_commit && (
            <p className="text-[9px] text-gray-700 mt-1 truncate" title={forja.last_commit}>
              {forja.last_commit.slice(20)}
            </p>
          )}
        </ProjectCard>

      </div>
    </div>
  );
}
