const DOT = {
  healthy:   'bg-green-400',
  open:      'bg-green-400',
  degraded:  'bg-yellow-400',
  connecting:'bg-yellow-400',
  critical:  'bg-red-400',
  close:     'bg-red-400',
  down:      'bg-red-400',
  error:     'bg-red-400',
  ghost:     'bg-yellow-400',
  unknown:   'bg-gray-500',
};

const LABEL = {
  healthy:    'Saudável',
  open:       'Conectado',
  degraded:   'Degradado',
  connecting: 'Conectando',
  critical:   'Crítico',
  close:      'Desconectado',
  down:       'Down',
  error:      'Erro',
  ghost:      'Fantasma',
  unknown:    'Desconhecido',
};

function Dot({ state }) {
  const cls = DOT[state] ?? DOT.unknown;
  return <span className={`inline-block w-2 h-2 rounded-full ${cls} flex-shrink-0`} />;
}

function Row({ label, state, detail }) {
  return (
    <div className="flex items-center gap-2 py-1.5 border-b border-white/5 last:border-0">
      <Dot state={state} />
      <span className="text-xs text-gray-300 w-32 flex-shrink-0">{label}</span>
      <span className={`text-[10px] font-semibold ${
        state === 'open' || state === 'healthy' ? 'text-green-400' :
        state === 'close' || state === 'down'   ? 'text-red-400'   :
        'text-yellow-400'
      }`}>
        {LABEL[state] ?? state}
      </span>
      {detail && <span className="text-[10px] text-gray-600 ml-auto truncate max-w-[140px]">{detail}</span>}
    </div>
  );
}

function fmtAgo(s) {
  if (s == null) return '—';
  if (s < 60)    return `${s}s`;
  if (s < 3600)  return `${Math.round(s/60)}min`;
  if (s < 86400) return `${(s/3600).toFixed(1)}h`;
  return `${(s/86400).toFixed(1)}d`;
}

function instanceState(inst) {
  const state = inst?.state ?? 'unknown';
  if (state === 'open') {
    const ago = inst?.last_msg_ago_s;
    if (ago != null && ago > 3600 * 2) return 'ghost';
  }
  return state;
}

export function ProductsStatus({ data }) {
  if (!data) return null;

  const sofia   = data.instances?.['sofia-mali']   ?? {};
  const viviane = data.instances?.['viviane-mali']  ?? {};
  const n8n     = data.n8n       ?? {};
  const skew    = data.clock_skew ?? {};
  const docker  = data.docker    ?? {};
  const lastMsg = data.last_msg  ?? {};

  const sofiaState   = instanceState(sofia);
  const vivianeState = viviane.state ?? 'unknown';

  const overallColor =
    data.overall === 'healthy'  ? 'text-green-400' :
    data.overall === 'degraded' ? 'text-yellow-400' : 'text-red-400';

  const skewDetail = skew.detected
    ? `${skew.skew_ms ?? '?'}ms fora de sync`
    : 'ok';

  const dockerDetail = `${docker.up ?? 0}/${docker.total_watched ?? 0} up`;

  const lastMsgDetail = lastMsg.ago_fmt
    ? `última: ${lastMsg.ago_fmt} atrás`
    : lastMsg.error ? 'erro ao consultar' : '—';

  return (
    <div className="bg-[#111633] border border-[#1f2a44] rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] font-black uppercase tracking-widest text-violet-400">
          Produtos — Mali Travel
        </span>
        <span className={`text-[10px] font-bold uppercase ${overallColor}`}>
          {data.overall ?? '—'}
        </span>
      </div>

      <div className="divide-y divide-white/5">
        {/* Instâncias WhatsApp */}
        <div className="pb-2 mb-1">
          <span className="text-[9px] uppercase tracking-widest text-gray-700 font-semibold">
            WhatsApp
          </span>
        </div>
        <Row
          label="sofia-mali"
          state={sofiaState}
          detail={sofiaState === 'ghost' ? `sem msg há ${fmtAgo(sofia.last_msg_ago_s ?? lastMsg.ago_s)}` : sofia.latency_ms ? `${sofia.latency_ms}ms` : null}
        />
        <Row
          label="viviane-mali"
          state={vivianeState}
          detail={vivianeState === 'close' ? 'precisa QR manual' : null}
        />

        {/* Infraestrutura */}
        <div className="pb-2 mb-1 mt-3">
          <span className="text-[9px] uppercase tracking-widest text-gray-700 font-semibold">
            Infraestrutura
          </span>
        </div>
        <Row
          label="n8n"
          state={n8n.up ? 'open' : 'down'}
          detail={n8n.latency_ms ? `${n8n.latency_ms}ms` : n8n.error ?? null}
        />
        <Row
          label="Clock skew"
          state={skew.detected ? (skew.skew_ms > 3000 ? 'down' : 'degraded') : 'open'}
          detail={skewDetail}
        />
        <Row
          label="Docker"
          state={docker.up >= docker.total_watched ? 'open' : docker.up === 0 ? 'down' : 'degraded'}
          detail={dockerDetail}
        />

        {/* base_mali */}
        <div className="pb-2 mb-1 mt-3">
          <span className="text-[9px] uppercase tracking-widest text-gray-700 font-semibold">
            Pipeline WhatsApp → DB
          </span>
        </div>
        <Row
          label="base_mali"
          state={
            !lastMsg.ago_s ? 'unknown' :
            lastMsg.ago_s < 3600      ? 'open' :
            lastMsg.ago_s < 3600 * 24 ? 'degraded' : 'down'
          }
          detail={lastMsgDetail}
        />
      </div>

      {data.timestamp && (
        <p className="text-[9px] text-gray-700 mt-3 text-right">
          atualizado {new Date(data.timestamp).toLocaleTimeString('pt-BR')}
        </p>
      )}
    </div>
  );
}
