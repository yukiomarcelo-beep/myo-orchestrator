import { useState, useEffect, useCallback, useRef } from 'react';
import { Sidebar } from '../layout/Sidebar';
import { Header }  from '../layout/Header';

// ── helpers ───────────────────────────────────────────────────────────────────

const brl = (v) =>
  'R$ ' + Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 0 });

async function apiFetch(path, opts = {}) {
  const res = await fetch('/api' + path, opts);
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

// ── design tokens ─────────────────────────────────────────────────────────────

const card  = 'bg-[#0f172a] border border-white/[0.07] rounded-xl p-4 mb-4';
const label = 'text-[11px] font-bold uppercase tracking-widest text-violet-400 mb-3';

const btn = {
  primary:   'flex-1 py-2 px-3 rounded-lg text-[11px] font-bold bg-gradient-to-br from-violet-600 to-purple-500 text-white hover:from-violet-500 hover:to-purple-400 transition-all disabled:opacity-40 disabled:cursor-not-allowed',
  secondary: 'flex-1 py-2 px-3 rounded-lg text-[11px] font-bold bg-white/5 border border-white/10 text-gray-400 hover:bg-white/10 hover:text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed',
  blue:      'flex-1 py-2 px-3 rounded-lg text-[11px] font-bold bg-sky-600/20 text-sky-300 border border-sky-500/20 hover:bg-sky-600/30 transition-all disabled:opacity-40 disabled:cursor-not-allowed',
  green:     'flex-1 py-2 px-3 rounded-lg text-[11px] font-bold bg-emerald-600/20 text-emerald-300 border border-emerald-500/20 hover:bg-emerald-600/30 transition-all disabled:opacity-40 disabled:cursor-not-allowed',
  ghost:     'py-2 px-3 rounded-lg text-[11px] font-bold bg-white/[0.03] border border-white/[0.06] text-gray-400 hover:bg-white/[0.07] hover:text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed',
};

// ── Modal System ──────────────────────────────────────────────────────────────

const MODAL_CONFIGS = {
  idea: {
    title: 'Nova Ideia de Produto',
    fields: [
      { key: 'nicho',    label: 'Nicho / Mercado',      placeholder: 'ex: finanças para millennials' },
      { key: 'formato',  label: 'Formato',               type: 'select', options: ['Curso', 'Ebook', 'Mentoria', 'Template', 'SaaS'] },
      { key: 'budget',   label: 'Budget estimado (R$)',  type: 'number', placeholder: '500' },
    ],
  },
  market: {
    title: 'Análise de Mercado',
    fields: [
      { key: 'produto',      label: 'Produto / Keyword',              placeholder: 'ex: curso de Excel' },
      { key: 'concorrentes', label: 'Concorrentes (vírgula)',          placeholder: 'ex: Hotmart, Udemy' },
    ],
  },
  content: {
    title: 'Gerar Conteúdo',
    fields: [
      { key: 'tema', label: 'Tema',        placeholder: 'ex: renda extra online' },
      { key: 'canal', label: 'Canal',      type: 'select', options: ['Instagram', 'YouTube', 'LinkedIn', 'Twitter/X', 'Blog'] },
      { key: 'tom',  label: 'Tom de voz', type: 'select', options: ['Educativo', 'Inspiracional', 'Técnico', 'Humorístico'] },
    ],
  },
  scenario: {
    title: 'Simular Cenário',
    fields: [
      { key: 'receita',      label: 'Receita mensal (R$)',        type: 'number', placeholder: '10000' },
      { key: 'custo',        label: 'Custo mensal (R$)',          type: 'number', placeholder: '3000' },
      { key: 'crescimento',  label: 'Crescimento esperado (%/mês)', type: 'number', placeholder: '15' },
    ],
  },
  lead: {
    title: 'Qualificar Lead',
    fields: [
      { key: 'nome',      label: 'Nome / Empresa',     placeholder: 'ex: João Silva' },
      { key: 'fonte',     label: 'Fonte',              type: 'select', options: ['Indicação', 'Instagram', 'LinkedIn', 'Website', 'Email'] },
      { key: 'interesse', label: 'Interesse declarado', placeholder: 'ex: consultoria de marketing' },
    ],
  },
  margin: {
    title: 'Análise de Margem',
    fields: [
      { key: 'produto',            label: 'Produto',              placeholder: 'ex: Curso Python Avançado' },
      { key: 'preco',              label: 'Preço de venda (R$)',  type: 'number', placeholder: '497' },
      { key: 'custo_fixo',         label: 'Custo fixo (R$)',      type: 'number', placeholder: '200' },
      { key: 'custo_variavel_pct', label: 'Custo variável (%)',   type: 'number', placeholder: '30' },
    ],
  },
};

function Modal({ type, onClose, onConfirm }) {
  const config = MODAL_CONFIGS[type];
  const [form, setForm] = useState({});
  const [running, setRunning] = useState(false);

  if (!config) return null;

  function setField(key, val) { setForm(p => ({ ...p, [key]: val })); }

  async function submit() {
    setRunning(true);
    try { await onConfirm(form); } catch {}
    setRunning(false);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-[#0f172a] border border-white/10 rounded-2xl p-6 w-full max-w-md mx-4 shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-[13px] font-bold text-white">{config.title}</h2>
          <button onClick={onClose} className="text-gray-600 hover:text-gray-300 text-xl leading-none transition-colors">×</button>
        </div>

        <div className="flex flex-col gap-3 mb-5">
          {config.fields.map(f => (
            <div key={f.key}>
              <label className="block text-[10px] font-semibold text-gray-600 uppercase tracking-wider mb-1">{f.label}</label>
              {f.type === 'select' ? (
                <select
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-[12px] text-white focus:outline-none focus:border-violet-500/50 transition-colors"
                  onChange={e => setField(f.key, e.target.value)}
                >
                  <option value="">Selecionar...</option>
                  {f.options.map(o => <option key={o} value={o.toLowerCase()}>{o}</option>)}
                </select>
              ) : (
                <input
                  type={f.type || 'text'}
                  placeholder={f.placeholder}
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-[12px] text-white placeholder-gray-700 focus:outline-none focus:border-violet-500/50 transition-colors"
                  onChange={e => setField(f.key, e.target.value)}
                />
              )}
            </div>
          ))}
        </div>

        <div className="flex gap-2">
          <button onClick={onClose} className={btn.secondary}>Cancelar</button>
          <button onClick={submit} disabled={running} className={btn.primary}>
            {running ? 'Processando...' : 'Executar'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── ProgressPanel (fixed bottom-right) ───────────────────────────────────────

const PIPELINE_STAGES = [
  { id: 'analise',   label: 'Análise'    },
  { id: 'ideacao',   label: 'Ideação'    },
  { id: 'validacao', label: 'Validação'  },
  { id: 'execucao',  label: 'Execução'   },
  { id: 'revisao',   label: 'Revisão'    },
];

function ProgressPanel({ pipeline }) {
  if (!pipeline?.fase) return null;

  const currentIdx = PIPELINE_STAGES.findIndex(s => s.id === pipeline.fase);
  const pct = pipeline.progresso || 0;

  return (
    <div className="fixed bottom-6 right-6 w-72 bg-[#0f172a] border border-white/[0.07] rounded-2xl p-4 shadow-2xl z-40">
      <div className="flex items-center justify-between mb-3">
        <p className="text-[10px] font-bold uppercase tracking-widest text-violet-400">Pipeline</p>
        {pipeline.produto && (
          <span className="text-[10px] text-violet-300 font-semibold truncate max-w-[110px]">{pipeline.produto}</span>
        )}
      </div>

      <div className="flex flex-col gap-2 mb-3">
        {PIPELINE_STAGES.map((s, i) => {
          const done   = i < currentIdx;
          const active = i === currentIdx;
          return (
            <div key={s.id} className="flex items-center gap-2.5">
              <div className={`w-4 h-4 rounded-full flex items-center justify-center flex-shrink-0 transition-all ${
                done   ? 'bg-violet-600' :
                active ? 'bg-violet-600/30 ring-2 ring-violet-500/60' :
                         'bg-white/[0.04]'
              }`}>
                {done   && <span className="text-white text-[8px] font-black">✓</span>}
                {active && <div className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />}
              </div>
              <span className={`text-[11px] transition-colors ${
                done ? 'text-gray-600' : active ? 'text-white font-semibold' : 'text-gray-800'
              }`}>{s.label}</span>
            </div>
          );
        })}
      </div>

      {pct > 0 && (
        <div className="h-1 bg-white/5 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-violet-600 to-purple-400 rounded-full transition-all duration-700"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
    </div>
  );
}

// ── Loader (fixed bottom-left) ────────────────────────────────────────────────

function Loader({ visible, label }) {
  if (!visible) return null;
  return (
    <div className="fixed bottom-6 left-[15rem] bg-[#0f172a] border border-white/[0.07] rounded-xl px-4 py-3 flex items-center gap-3 shadow-2xl z-40">
      <div className="w-4 h-4 rounded-full border-2 border-violet-500 border-t-transparent animate-spin flex-shrink-0" />
      <span className="text-[11px] text-gray-400">{label || 'Processando...'}</span>
    </div>
  );
}

// ── GovernancePanel ───────────────────────────────────────────────────────────

const MODE_CONFIG = {
  manual:    { label: 'Manual',    color: 'text-gray-400',   border: 'border-gray-500',   bg: 'bg-gray-500/10' },
  assistido: { label: 'Assistido', color: 'text-sky-400',    border: 'border-sky-500',    bg: 'bg-sky-500/10'  },
  autonomo:  { label: 'Autônomo',  color: 'text-yellow-400', border: 'border-yellow-500', bg: 'bg-yellow-500/10' },
};

function GovernancePanel() {
  const [mode,    setMode]    = useState(null);
  const [config,  setConfig]  = useState(null);
  const [saving,  setSaving]  = useState(false);
  const [editing, setEditing] = useState(false);
  const [limits,  setLimits]  = useState({ limite_mensal: '', limite_por_acao: '' });

  useEffect(() => {
    apiFetch('/governance/mode')
      .then(d => setMode(d.modo))
      .catch(() =>
        apiFetch('/autonomous').then(d => {
          setMode({ 0: 'manual', 1: 'assistido', 2: 'autonomo' }[d.level] || 'manual');
        }).catch(() => {})
      );

    apiFetch('/governance/config').then(d => {
      setConfig(d);
      setLimits({ limite_mensal: d.limite_mensal || '', limite_por_acao: d.limite_por_acao || '' });
    }).catch(() => {});
  }, []);

  async function setModeVal(m) {
    setSaving(true);
    try {
      await apiFetch('/governance/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ modo: m }),
      });
      setMode(m);
    } catch {}
    setSaving(false);
  }

  async function saveConfig() {
    try {
      await apiFetch('/governance/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          limite_mensal:    Number(limits.limite_mensal),
          limite_por_acao:  Number(limits.limite_por_acao),
        }),
      });
      setEditing(false);
    } catch {}
  }

  const pct      = config?.pct_usado ?? 0;
  const barColor = pct > 80 ? 'bg-red-500' : pct > 60 ? 'bg-yellow-500' : 'bg-violet-500';
  const pctColor = pct > 80 ? 'text-red-400' : pct > 60 ? 'text-yellow-400' : 'text-violet-400';

  return (
    <div className={card}>
      <p className={label}>Modo de Autonomia</p>

      <div className="flex gap-2 mb-4">
        {Object.entries(MODE_CONFIG).map(([k, v]) => (
          <button
            key={k}
            onClick={() => setModeVal(k)}
            disabled={saving || mode === k}
            className={`flex-1 py-2 rounded-lg border text-[11px] font-bold transition-all disabled:opacity-40 disabled:cursor-not-allowed ${
              mode === k
                ? `${v.border} ${v.color} ${v.bg}`
                : 'border-white/10 text-gray-600 hover:border-white/20 hover:text-gray-400'
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>

      {config && (
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] text-gray-600">Budget do mês</span>
            <span className={`text-[10px] font-bold ${pctColor}`}>{pct.toFixed(0)}%</span>
          </div>
          <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
            <div
              className={`h-full ${barColor} rounded-full transition-all duration-700`}
              style={{ width: `${Math.min(pct, 100)}%` }}
            />
          </div>
          {config.limite_mensal > 0 && (
            <p className="text-[10px] text-gray-700 mt-1">
              {brl(config.gasto_mes || 0)} / {brl(config.limite_mensal)}
              {config.limite_por_acao > 0 && <> · máx/ação {brl(config.limite_por_acao)}</>}
            </p>
          )}
        </div>
      )}

      {editing ? (
        <div className="flex flex-col gap-2 pt-2 border-t border-white/[0.05]">
          <div className="grid grid-cols-2 gap-2">
            {[
              { key: 'limite_mensal',   lbl: 'Limite mensal' },
              { key: 'limite_por_acao', lbl: 'Limite/ação'   },
            ].map(f => (
              <div key={f.key}>
                <label className="text-[9px] text-gray-600 uppercase tracking-wider block mb-1">{f.lbl}</label>
                <input
                  type="number"
                  value={limits[f.key]}
                  placeholder="R$ 0"
                  onChange={e => setLimits(p => ({ ...p, [f.key]: e.target.value }))}
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-[11px] text-white focus:outline-none focus:border-violet-500/50 transition-colors"
                />
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <button onClick={() => setEditing(false)} className={btn.secondary}>Cancelar</button>
            <button onClick={saveConfig}              className={btn.primary}>Salvar</button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setEditing(true)}
          className="text-[10px] text-gray-700 hover:text-gray-400 transition-colors mt-1"
        >
          Configurar limites financeiros →
        </button>
      )}
    </div>
  );
}

// ── Batch Action Panel ────────────────────────────────────────────────────────

const BATCH_CHIPS = [
  { id: 'pipeline', label: 'Rodar Pipeline', icon: '⚡' },
  { id: 'simulate', label: 'Simular Ciclo',  icon: '◎' },
  { id: 'market',   label: 'Validar Mercado', icon: '◈' },
  { id: 'kaizen',   label: 'Rodar Kaizen',   icon: '↻' },
];

function BatchPanel({ onLoader }) {
  const [selected, setSelected] = useState([]);
  const [running,  setRunning]  = useState(false);

  function toggle(id) {
    setSelected(p => p.includes(id) ? p.filter(x => x !== id) : [...p, id]);
  }

  async function execute() {
    if (!selected.length) return;
    setRunning(true);
    onLoader(true, `Sequência: ${selected.join(' → ')}`);
    try {
      for (const id of selected) {
        await apiFetch('/run-batch-action', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ acao: id }),
        });
      }
    } catch {}
    setRunning(false);
    onLoader(false);
    setSelected([]);
  }

  return (
    <div className={card}>
      <p className={label}>Executar Sequência</p>
      <div className="flex flex-wrap gap-2 mb-3">
        {BATCH_CHIPS.map(c => (
          <button
            key={c.id}
            onClick={() => toggle(c.id)}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-full border text-[11px] font-semibold transition-all ${
              selected.includes(c.id)
                ? 'bg-violet-600/20 border-violet-500/50 text-violet-300 shadow-[0_0_10px_rgba(139,92,246,0.15)]'
                : 'bg-white/[0.03] border-white/10 text-gray-500 hover:text-gray-300 hover:border-white/20'
            }`}
          >
            <span className="text-[10px]">{c.icon}</span>
            {c.label}
          </button>
        ))}
      </div>
      <button
        onClick={execute}
        disabled={running || !selected.length}
        className={`w-full py-2.5 rounded-xl text-[12px] font-bold transition-all disabled:opacity-40 disabled:cursor-not-allowed ${
          selected.length
            ? 'bg-gradient-to-br from-violet-600 to-purple-500 text-white hover:from-violet-500 hover:to-purple-400 shadow-lg hover:shadow-violet-500/30'
            : 'bg-white/5 border border-white/10 text-gray-600'
        }`}
      >
        {running
          ? 'Executando...'
          : selected.length > 0
            ? `Executar Sequência (${selected.length})`
            : 'Selecione ações acima'}
      </button>
    </div>
  );
}

// ── Action Categories ─────────────────────────────────────────────────────────

const ACTION_CATEGORIES = [
  {
    id: 'ideia', label: 'Nova Ideia',
    accent: 'from-violet-600 to-purple-500',
    textColor: 'text-violet-400',
    actions: [
      { label: 'Avaliar ideia',    modal: 'idea',             icon: '✦', primary: true },
      { label: 'Rodar pipeline',   endpoint: 'run-pipeline',  icon: '⚡' },
      { label: 'Validar mercado',  modal: 'market',           icon: '◎' },
    ],
  },
  {
    id: 'conteudo', label: 'Conteúdo',
    accent: 'from-sky-600 to-blue-500',
    textColor: 'text-sky-400',
    actions: [
      { label: 'Registrar performance', modal: 'content',        icon: '✎', primary: true },
      { label: 'Simular ciclo',         modal: 'scenario',       icon: '◎' },
    ],
  },
  {
    id: 'leads', label: 'Leads',
    accent: 'from-emerald-600 to-green-500',
    textColor: 'text-emerald-400',
    actions: [
      { label: 'Novo lead',        modal: 'lead',            icon: '◈', primary: true },
      { label: 'Ver pipeline CRM', endpoint: 'run-followup', icon: '→' },
    ],
  },
  {
    id: 'financeiro', label: 'Financeiro',
    accent: 'from-amber-500 to-yellow-400',
    textColor: 'text-amber-400',
    actions: [
      { label: 'Calcular margem', modal: 'margin',        icon: '◉', primary: true },
      { label: 'Simular cenário', modal: 'scenario',      icon: '◇' },
    ],
  },
];

function ActionCategories({ onModal, onLoader }) {
  const [running, setRunning] = useState(null);

  async function runEndpoint(endpoint) {
    setRunning(endpoint);
    onLoader(true, `Executando ${endpoint}...`);
    try {
      await apiFetch('/' + endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
    } catch {}
    setTimeout(() => { setRunning(null); onLoader(false); }, 2000);
  }

  return (
    <div className={card}>
      <p className={label}>Ações Rápidas</p>
      <div className="flex flex-col gap-5">
        {ACTION_CATEGORIES.map(cat => (
          <div key={cat.id}>
            <div className="flex items-center gap-2 mb-2">
              <span className={`text-[10px] font-bold uppercase tracking-widest ${cat.textColor}`}>{cat.label}</span>
              <div className="flex-1 h-px bg-white/[0.05]" />
            </div>
            <div className="flex flex-wrap gap-2">
              {cat.actions.map(a => (
                <button
                  key={a.label}
                  onClick={() => a.modal ? onModal(a.modal) : runEndpoint(a.endpoint)}
                  disabled={running === a.endpoint}
                  className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-[12px] font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed ${
                    a.primary
                      ? `bg-gradient-to-br ${cat.accent} text-white shadow-lg hover:opacity-90 hover:shadow-xl active:scale-95`
                      : 'bg-white/[0.04] border border-white/[0.08] text-gray-300 hover:bg-white/[0.07] hover:border-white/[0.15] hover:text-white active:scale-95'
                  }`}
                >
                  <span className="text-[10px]">{a.icon}</span>
                  {running === a.endpoint ? '...' : a.label}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Approval Queue ────────────────────────────────────────────────────────────

const IMPACT = {
  alto:  'bg-red-500/15 text-red-400 border-red-500/20',
  medio: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/20',
  baixo: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
};

function inferImpact(item) {
  if (item.impacto) return item.impacto;
  const custo = item.financeiro?.custo_estimado || 0;
  return custo > 500 ? 'alto' : custo > 100 ? 'medio' : 'baixo';
}

function ApprovalQueue() {
  const [items,   setItems]   = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    apiFetch('/pending')
      .then(d => { setItems(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  async function decide(id, action) {
    try {
      await apiFetch(`/${action}/${id}`, { method: 'POST' });
      load();
    } catch {}
  }

  return (
    <div className={card}>
      <div className="flex items-center justify-between mb-3">
        <p className={label.replace('mb-3', '')}>Fila de Aprovação</p>
        {items.length > 0 && (
          <span className="text-[10px] bg-violet-600/20 text-violet-400 px-2 py-0.5 rounded-full border border-violet-500/20 font-bold">
            {items.length}
          </span>
        )}
      </div>

      {loading ? (
        <p className="text-[11px] text-gray-700">Carregando...</p>
      ) : items.length === 0 ? (
        <p className="text-[11px] text-gray-700">Nenhuma ação pendente.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {items.map(item => {
            const impact = inferImpact(item);
            return (
              <div key={item.id} className="bg-white/[0.02] border border-white/[0.05] rounded-xl p-3">
                <div className="flex items-start justify-between gap-2 mb-1.5">
                  <p className="text-[12px] font-semibold text-white leading-snug">{item.acao}</p>
                  <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border flex-shrink-0 ${IMPACT[impact] || IMPACT.baixo}`}>
                    {impact}
                  </span>
                </div>

                {item.motivo && (
                  <p className="text-[10px] text-gray-600 mb-2 leading-relaxed">{item.motivo}</p>
                )}

                {(item.financeiro?.custo_estimado > 0 || item.financeiro?.roi_pct) && (
                  <div className="flex items-center gap-3 mb-2.5">
                    {item.financeiro?.custo_estimado > 0 && (
                      <span className="text-[10px] text-yellow-400 font-semibold">{brl(item.financeiro.custo_estimado)}</span>
                    )}
                    {item.financeiro?.roi_pct && (
                      <span className="text-[10px] text-emerald-400 font-semibold">ROI {item.financeiro.roi_pct}%</span>
                    )}
                  </div>
                )}

                <div className="flex gap-2">
                  <button
                    onClick={() => decide(item.id, 'approve')}
                    className="flex-1 py-1.5 rounded-lg bg-emerald-600/15 text-emerald-400 text-[10px] font-bold hover:bg-emerald-600/25 transition-all border border-emerald-500/20"
                  >
                    Aprovar
                  </button>
                  <button
                    onClick={() => decide(item.id, 'reject')}
                    className="flex-1 py-1.5 rounded-lg bg-red-600/10 text-red-400 text-[10px] font-bold hover:bg-red-600/20 transition-all border border-red-500/20"
                  >
                    Rejeitar
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── AI Suggestions ────────────────────────────────────────────────────────────

function AISuggestions({ onLoader }) {
  const [items,   setItems]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(null);

  useEffect(() => {
    apiFetch('/suggest-actions')
      .then(d => { setItems(Array.isArray(d) ? d : []); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  async function runAction(item) {
    setRunning(item.titulo);
    onLoader(true, `IA: ${item.titulo}`);
    try {
      await apiFetch('/' + item.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(item.params || {}),
      });
    } catch {}
    setTimeout(() => { setRunning(null); onLoader(false); }, 2000);
  }

  return (
    <div className={card}>
      <p className={label}>IA Recomenda</p>
      {loading ? (
        <p className="text-[11px] text-gray-700">Analisando...</p>
      ) : items.length === 0 ? (
        <p className="text-[11px] text-gray-700">Nenhuma sugestão no momento.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {items.slice(0, 5).map((item, i) => (
            <div key={i} className="flex items-center gap-3 bg-white/[0.02] border border-white/[0.04] rounded-xl p-3">
              <div className="flex-1 min-w-0">
                <p className="text-[12px] font-semibold text-white">{item.titulo}</p>
                {item.motivo && (
                  <p className="text-[10px] text-gray-600 mt-0.5 truncate">{item.motivo}</p>
                )}
              </div>
              <button
                onClick={() => runAction(item)}
                disabled={running === item.titulo}
                className="flex-shrink-0 px-3 py-1.5 rounded-lg text-[10px] font-bold bg-violet-600/15 text-violet-300 hover:bg-violet-600/25 transition-all disabled:opacity-40 border border-violet-500/20"
              >
                {running === item.titulo ? '...' : 'Executar'}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Pipeline Controls ─────────────────────────────────────────────────────────

function PipelineControls({ onPipelineStatus, onLoader }) {
  const [status, setStatus] = useState(null);
  const [busy,   setBusy]   = useState(false);
  const cbRef = useRef(onPipelineStatus);
  useEffect(() => { cbRef.current = onPipelineStatus; });

  useEffect(() => {
    apiFetch('/pipeline').then(d => { setStatus(d); cbRef.current?.(d); }).catch(() => {});
  }, []);

  async function run(endpoint, loaderLabel) {
    setBusy(true);
    onLoader(true, loaderLabel);
    try {
      await apiFetch('/' + endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ objetivo: status?.produto || 'auto', modo: 'auto' }),
      });
    } catch {}
    setTimeout(() => { setBusy(false); onLoader(false); }, 3000);
  }

  return (
    <div className={card}>
      <p className={label}>Pipeline</p>

      {status?.fase && (
        <div className="flex items-center gap-2 mb-3 bg-white/[0.02] rounded-lg px-3 py-2 border border-white/[0.04]">
          <div className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse flex-shrink-0" />
          <span className="text-[10px] text-gray-500">Fase:</span>
          <span className="text-[11px] text-violet-300 font-semibold">{status.fase_label || status.fase}</span>
          {status.produto && (
            <span className="text-[10px] text-gray-600 ml-auto truncate max-w-[120px]">{status.produto}</span>
          )}
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={() => run('run-pipeline', 'Rodando pipeline...')}
          disabled={busy}
          className={btn.primary}
        >
          {busy ? 'Iniciando...' : 'Rodar Pipeline'}
        </button>
        <button
          onClick={() => run('run-kaizen', 'Executando Kaizen...')}
          disabled={busy}
          className={btn.blue}
        >
          Kaizen
        </button>
      </div>
    </div>
  );
}

// ── Execution Log ─────────────────────────────────────────────────────────────

const PRODUCT_PALETTE = [
  'text-violet-400', 'text-sky-400', 'text-emerald-400', 'text-amber-400',
  'text-pink-400',   'text-teal-400', 'text-orange-400',  'text-cyan-400',
];

function ExecutionLog() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const colorMap = useRef({});
  const idx      = useRef(0);

  function productColor(name) {
    if (!name) return 'text-gray-600';
    if (!colorMap.current[name]) {
      colorMap.current[name] = PRODUCT_PALETTE[idx.current % PRODUCT_PALETTE.length];
      idx.current++;
    }
    return colorMap.current[name];
  }

  const load = useCallback(() => {
    apiFetch('/log?n=30')
      .then(d => { setEntries(Array.isArray(d) ? d : []); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);

  const statusIcon  = s => s === 'ok' ? '✓' : s === 'warn' ? '!' : s === 'erro' ? '✗' : '·';
  const statusColor = s =>
    s === 'ok'   ? 'text-emerald-400' :
    s === 'warn' ? 'text-yellow-400'  :
    s === 'erro' ? 'text-red-400'     : 'text-gray-700';

  return (
    <div className={card}>
      <div className="flex items-center justify-between mb-3">
        <p className={label.replace('mb-3', '')}>Log de Atividade</p>
        <button onClick={load} className="text-[10px] text-gray-700 hover:text-gray-500 transition-colors">↻</button>
      </div>

      {loading ? (
        <p className="text-[11px] text-gray-700">Carregando...</p>
      ) : entries.length === 0 ? (
        <p className="text-[11px] text-gray-700">Nenhum evento registrado.</p>
      ) : (
        <div className="flex flex-col max-h-72 overflow-y-auto pr-1">
          {entries.map((e, i) => (
            <div key={i} className="flex items-start gap-2 py-1.5 border-b border-white/[0.04] last:border-0">
              <span className={`flex-shrink-0 font-bold text-[11px] mt-px w-3 text-center ${statusColor(e.status)}`}>
                {statusIcon(e.status)}
              </span>
              <span className={`text-[10px] font-semibold flex-shrink-0 ${productColor(e.produto)}`}>
                {e.produto || 'Sistema'}
              </span>
              <span className="text-[11px] text-gray-400 flex-1 leading-relaxed min-w-0 truncate">{e.evento}</span>
              <span className="text-[10px] font-mono text-gray-700 flex-shrink-0 mt-px">
                {e.ts ? (() => { const d = new Date(String(e.ts).replace(' ', 'T')); return isNaN(d) ? e.ts.slice(11, 16) || '' : d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }); })() : ''}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Hero ──────────────────────────────────────────────────────────────────────

function Hero({ pipeline }) {
  const biz = pipeline?.produto;
  return (
    <div className="flex items-start justify-between gap-3 mb-6 flex-wrap">
      <div>
        <h1 className="text-xl font-black text-white tracking-tight mb-0.5">Centro de Controle</h1>
        <p className="text-[12px] text-gray-500">Pipeline · Leads · Conteúdo · Financeiro — com progresso real e sugestões de IA</p>
      </div>
      {biz && (
        <div className="flex items-center gap-2 bg-violet-600/10 border border-violet-500/25 rounded-xl px-3 py-2 flex-shrink-0">
          <div className="w-2 h-2 rounded-full bg-violet-400 shadow-[0_0_6px_#a78bfa] flex-shrink-0" />
          <span className="text-[12px] font-bold text-violet-300">{biz}</span>
        </div>
      )}
    </div>
  );
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function Operations() {
  const [lastUpdate, setLastUpdate] = useState(new Date());
  const [modal,    setModal]    = useState(null);
  const [loader,   setLoader]   = useState({ visible: false, label: '' });
  const [pipeline, setPipeline] = useState(null);

  const reload = () => setLastUpdate(new Date());

  function showLoader(visible, label = '') { setLoader({ visible, label }); }

  async function handleModalConfirm(form) {
    await apiFetch('/run-action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tipo: modal, params: form }),
    }).catch(() => {});
  }

  return (
    <div className="flex h-screen bg-[#0a0e27] text-white overflow-hidden">
      <Sidebar />

      <main className="flex-1 p-6 overflow-y-auto">
        <Header lastUpdate={lastUpdate} onReload={reload} title="Operações" />

        <div className="max-w-xl mx-auto">
          <Hero pipeline={pipeline} />
          <GovernancePanel />
          <ApprovalQueue />
          <AISuggestions onLoader={showLoader} />
          <BatchPanel onLoader={showLoader} />
          <ActionCategories onModal={setModal} onLoader={showLoader} />
          <PipelineControls onPipelineStatus={setPipeline} onLoader={showLoader} />
          <ExecutionLog />
        </div>
      </main>

      {modal && (
        <Modal type={modal} onClose={() => setModal(null)} onConfirm={handleModalConfirm} />
      )}

      <ProgressPanel pipeline={pipeline} />
      <Loader visible={loader.visible} label={loader.label} />
    </div>
  );
}
