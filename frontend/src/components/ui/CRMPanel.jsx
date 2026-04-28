const TEMP = {
  quente: { dot: 'bg-red-400',    text: 'text-red-400',    label: 'Quente' },
  morno:  { dot: 'bg-yellow-400', text: 'text-yellow-400', label: 'Morno'  },
  frio:   { dot: 'bg-sky-400',    text: 'text-sky-400',    label: 'Frio'   },
};

const STAGE_LABEL = {
  qualificado: 'Qualificado',
  prospecto:   'Prospecto',
  negociacao:  'Negociação',
  fechado:     'Fechado',
  perdido:     'Perdido',
};

const SOURCE_LABEL = {
  instagram_bio:  'Instagram',
  stories_link:   'Stories',
  feed_instagram: 'Instagram',
  carrossel_cfo:  'Orgânico',
  carrossel:      'Orgânico',
  linkedin:       'LinkedIn',
  indicacao:      'Indicação',
  referral:       'Indicação',
  website:        'Website',
  blog:           'Website',
  email:          'Email',
};

function ScoreBar({ score }) {
  const color = score >= 75 ? 'bg-emerald-500' : score >= 50 ? 'bg-yellow-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 bg-white/5 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${score}%` }} />
      </div>
      <span className="text-[10px] font-bold text-gray-400 w-5 text-right">{score}</span>
    </div>
  );
}

export function CRMPanel({ leads = [] }) {
  if (!leads.length) return (
    <div className="bg-[#111633] border border-[#1f2a44] rounded-xl p-4 mb-5">
      <p className="text-[10px] font-black uppercase tracking-widest text-emerald-400 mb-2">CRM — Leads</p>
      <p className="text-[11px] text-gray-700">Nenhum lead registrado.</p>
    </div>
  );

  const sorted = [...leads].sort((a, b) => (b.score ?? 0) - (a.score ?? 0));

  return (
    <div className="bg-[#111633] border border-[#1f2a44] rounded-xl p-4 mb-5">
      <div className="flex items-center justify-between mb-3">
        <p className="text-[10px] font-black uppercase tracking-widest text-emerald-400">
          CRM — Leads
        </p>
        <span className="text-[10px] text-gray-600">{leads.length} registros</span>
      </div>

      <div className="flex flex-col gap-2">
        {sorted.map((lead, i) => {
          const temp = TEMP[lead.temperature] || TEMP.frio;
          const preview = lead.followup_sequence?.[0]?.message?.slice(0, 80);
          const source  = SOURCE_LABEL[lead.source] || lead.source || '—';
          const stage   = STAGE_LABEL[lead.pipeline_stage] || lead.pipeline_stage || '—';

          return (
            <div key={lead.lead_id || i} className="bg-[#0d1526] border border-[#1f2a44] rounded-xl p-3">
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="flex items-center gap-2 min-w-0">
                  <div className={`w-2 h-2 rounded-full flex-shrink-0 ${temp.dot}`} />
                  <span className="text-[12px] font-semibold text-white truncate">{lead.name}</span>
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <span className={`text-[9px] font-bold uppercase ${temp.text}`}>{temp.label}</span>
                  <span className="text-[9px] text-gray-700">·</span>
                  <span className="text-[9px] text-gray-500">{source}</span>
                </div>
              </div>

              <ScoreBar score={lead.score ?? 0} />

              <div className="flex items-center gap-2 mt-2">
                <span className="text-[9px] font-semibold bg-violet-600/15 text-violet-400 px-1.5 py-0.5 rounded border border-violet-500/20">
                  {lead.idea_title || '—'}
                </span>
                <span className="text-[9px] text-gray-600">{stage}</span>
              </div>

              {preview && (
                <p className="text-[10px] text-gray-600 mt-2 leading-relaxed line-clamp-2">
                  "{preview}..."
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
