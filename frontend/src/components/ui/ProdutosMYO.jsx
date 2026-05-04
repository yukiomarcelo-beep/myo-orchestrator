const STATUS_CFG = {
  rodando: { dot: 'bg-amber-400 animate-pulse', text: 'text-amber-400',  label: 'Rodando'  },
  done:    { dot: 'bg-green-400',               text: 'text-green-400',  label: 'Concluído' },
  error:   { dot: 'bg-red-400',                 text: 'text-red-400',    label: 'Erro'      },
  idle:    { dot: 'bg-gray-600',                text: 'text-gray-600',   label: 'Idle'      },
};

const FASE_LABEL = {
  opportunity: 'Oportunidade', product: 'Produto', content: 'Conteúdo',
  video: 'Vídeo', sales: 'Vendas', performance: 'Performance', idle: 'Aguardando',
};

function fmtTs(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    const diffD = Math.floor((Date.now() - d) / 86400000);
    if (diffD === 0) return 'hoje';
    if (diffD === 1) return 'ontem';
    return `${diffD}d atrás`;
  } catch { return '—'; }
}

function ProdutoRow({ p }) {
  const st  = STATUS_CFG[p.status] ?? STATUS_CFG.idle;
  const nome = p.produto || 'Sem nome';
  const fase = FASE_LABEL[p.fase_atual] ?? p.fase_atual ?? '—';
  const prog = p.progresso ?? 0;

  return (
    <div className="flex items-center gap-3 py-2.5 border-b border-white/[0.05] last:border-0 group">
      <div className={`w-2 h-2 rounded-full flex-shrink-0 ${st.dot}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[12px] font-semibold text-white truncate">{nome}</span>
          <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded ${st.text} bg-white/5`}>
            {st.label}
          </span>
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-[10px] text-gray-600">{fase}</span>
          {prog > 0 && (
            <>
              <span className="text-[10px] text-gray-700">·</span>
              <div className="flex items-center gap-1">
                <div className="w-16 h-1 bg-white/5 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      p.status === 'error' ? 'bg-red-500' :
                      p.status === 'done'  ? 'bg-green-500' : 'bg-amber-500'
                    }`}
                    style={{ width: `${Math.min(prog, 100)}%` }}
                  />
                </div>
                <span className="text-[10px] text-gray-700">{prog}%</span>
              </div>
            </>
          )}
        </div>
      </div>
      <span className="text-[10px] text-gray-700 flex-shrink-0">{fmtTs(p.timestamp)}</span>
    </div>
  );
}

function BizRow({ b }) {
  const brl = (v) => 'R$ ' + Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 0 });
  const isActive = b.status === 'rodando' || b.status === 'ativo';

  return (
    <div className="flex items-center gap-3 py-2 border-b border-white/[0.05] last:border-0">
      <div
        className="w-2.5 h-2.5 rounded-full flex-shrink-0"
        style={{ backgroundColor: b.cor || '#7c3aed', boxShadow: isActive ? `0 0 6px ${b.cor || '#7c3aed'}88` : 'none' }}
      />
      <span className="text-[12px] font-semibold text-white flex-1 truncate">{b.nome}</span>
      <span className="text-[11px] text-gray-500">{FASE_LABEL[b.fase] ?? b.fase ?? '—'}</span>
      {b.receita > 0 && (
        <span className="text-[11px] font-semibold text-green-400 flex-shrink-0">{brl(b.receita)}</span>
      )}
    </div>
  );
}

export function ProdutosMYO({ state, businesses }) {
  const produtos   = state?.produtos ?? [];
  const bizList    = businesses ?? [];
  const ativos     = produtos.filter(p => p.status === 'rodando').length;
  const comErro    = produtos.filter(p => p.status === 'error').length;

  if (!produtos.length && !bizList.length) return null;

  return (
    <div className="bg-[#111633] border border-[#1f2a44] rounded-xl p-4 mb-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] font-black uppercase tracking-widest text-violet-400">
          Produtos — Engines MYO
        </span>
        <div className="flex items-center gap-2">
          {ativos > 0 && (
            <span className="text-[9px] bg-amber-500/15 text-amber-400 border border-amber-500/20 px-1.5 py-0.5 rounded font-bold">
              {ativos} rodando
            </span>
          )}
          {comErro > 0 && (
            <span className="text-[9px] bg-red-500/15 text-red-400 border border-red-500/20 px-1.5 py-0.5 rounded font-bold">
              {comErro} com erro
            </span>
          )}
        </div>
      </div>

      {/* Pipeline MYO */}
      {produtos.length > 0 && (
        <div className="mb-4">
          <span className="text-[9px] uppercase tracking-widest text-gray-700 font-semibold">
            Pipeline / Runs
          </span>
          <div className="mt-1">
            {produtos.map((p, i) => <ProdutoRow key={i} p={p} />)}
          </div>
        </div>
      )}

      {/* Businesses */}
      {bizList.length > 0 && (
        <div>
          <span className="text-[9px] uppercase tracking-widest text-gray-700 font-semibold">
            Portfolio de Negócios
          </span>
          <div className="mt-1">
            {bizList.map((b) => <BizRow key={b.id} b={b} />)}
          </div>
        </div>
      )}
    </div>
  );
}
